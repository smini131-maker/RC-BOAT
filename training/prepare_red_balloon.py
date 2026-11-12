"""Prepare red-balloon fine-tuning views without moving any source between splits."""
import argparse
import json
import random
import shutil
from pathlib import Path

import cv2
import numpy as np
import yaml

from prepare_small_objects import boxes_for, crop_view, read_image, save_view


def red_mask(hsv, saturation=75, value=38):
    h, s, v = cv2.split(hsv)
    return ((h <= 12) | (h >= 170)) & (s >= saturation) & (v >= value)


def red_indices(frame, boxes):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    indices = []
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        # Inner rectangle discounts the box background and balloon strings.
        dx, dy = (x2-x1)*.2, (y2-y1)*.2
        inner = hsv[max(0, int(y1+dy)):int(y2-dy), max(0, int(x1+dx)):int(x2-dx)]
        if inner.size and red_mask(inner).mean() >= .55:
            indices.append(i)
    return indices


def expose(frame, rng, lighting):
    rgb = frame.astype(np.float32) / 255
    if lighting == 'dim':
        rgb = rgb ** rng.uniform(1.08, 1.40) * rng.uniform(.45, .77)
    elif lighting == 'bright':
        rgb = rgb ** rng.uniform(.65, .9) * rng.uniform(1.08, 1.32)
    else:
        rgb = rgb ** rng.uniform(.94, 1.08) * rng.uniform(.87, 1.12)
    rgb *= np.array([rng.uniform(.90, 1.10), rng.uniform(.94, 1.04), rng.uniform(.94, 1.08)])
    return np.uint8(np.clip(rgb * 255, 0, 255))


def negative_crop(frame, boxes, rng):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = red_mask(hsv).astype(np.uint8)
    _, _, regions, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    h, w = frame.shape[:2]
    for x, y, bw, bh, area in sorted(regions[1:], key=lambda r: -r[4])[:14]:
        if area < 35 or area > w*h*.20:
            continue
        side = min(max(72, 3*max(bw, bh)), w, h, 640)
        left = max(0, min(w-side, x+bw//2-side//2))
        top = max(0, min(h-side, y+bh//2-side//2))
        right, bottom = left+side, top+side
        if any(min(right, x2)>max(left, x1) and min(bottom, y2)>max(top, y1)
               for x1,y1,x2,y2 in boxes):
            continue
        return expose(cv2.resize(frame[top:bottom, left:right], (320,320)), rng,
                      rng.choice(('dim','bright','neutral')))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    if out.exists():
        raise FileExistsError(out)
    cv2.setNumThreads(2)
    rng = random.Random(2410)
    counts, records, seen = {}, {}, set()
    for split in ('train', 'val', 'test'):
        for sub in ('images','labels'):
            (out/sub/split).mkdir(parents=True)
        counts[split] = dict(originals=0, red_originals=0, red_boxes=0,
                             bright_views=0, dim_views=0, red_background_crops=0)
        info = counts[split]
        for photo in sorted((source/'images'/split).glob('*.jpg')):
            if photo.stem in seen:
                raise ValueError('source ID in multiple splits: '+photo.stem)
            seen.add(photo.stem)
            label = source/'labels'/split/(photo.stem+'.txt')
            shutil.copy2(photo, out/'images'/split/photo.name)
            shutil.copy2(label, out/'labels'/split/label.name)
            info['originals'] += 1
            frame = read_image(photo)
            if frame is None:
                raise ValueError('unreadable image: '+str(photo))
            boxes = boxes_for(label, frame.shape)
            indices = red_indices(frame, boxes)
            if indices:
                info['red_originals'] += 1
                info['red_boxes'] += len(indices)
                records[photo.stem] = dict(split=split, red_boxes=indices)
                if split == 'train':
                    index = rng.choice(indices)
                    for lighting in ('bright','dim'):
                        view, labels = crop_view(frame, boxes, index, rng)
                        if labels:
                            name = photo.stem+'_'+lighting
                            save_view(out, split, name, expose(view, rng, lighting), labels)
                            info[lighting+'_views'] += 1
            if split == 'train' and info['red_background_crops'] < 350:
                negative = negative_crop(frame, boxes, rng)
                if negative is not None:
                    save_view(out, split, photo.stem+'_background', negative, [])
                    info['red_background_crops'] += 1
    spec = dict(path=str(out), train='images/train', val='images/val', test='images/test', names={0:'balloon'})
    (out/'data.yaml').write_text(yaml.safe_dump(spec), encoding='utf-8')
    source_metadata = json.loads((source/'dataset_source.json').read_text(encoding='utf-8'))
    metadata = dict(source={k: source_metadata[k] for k in
                    ('dataset','class_id','annotations_url','split_method') if k in source_metadata},
                    counts=counts, red_selection='HSV screening of annotated boxes; not manual colour labels',
                    target_reference='red swatch only; no competition photos used', seed=2410,
                    red_candidate_records=records)
    (out/'dataset_source.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(counts, indent=2), flush=True)


if __name__ == '__main__':
    main()
