"""Object-scale views and mined negatives, preserving original image-group splits.

Generated views are augmentation, never additional original photographs or measured
distance data. No validation/test source image is used in training.
"""
import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

import cv2
import numpy as np
import yaml


def read_image(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def boxes_for(path, shape):
    h, w = shape[:2]
    rows = []
    for line in path.read_text().splitlines():
        _, x, y, bw, bh = map(float, line.split())
        rows.append([(x-bw/2)*w, (y-bh/2)*h, (x+bw/2)*w, (y+bh/2)*h])
    return rows


def crop_view(frame, boxes, index, rng):
    h, w = frame.shape[:2]
    b = boxes[index]
    target_px = rng.choice((16, 24, 32, 48, 64, 96, 128))
    side = max(40, min(max(w, h)*1.25, max(b[2]-b[0], b[3]-b[1])*320/target_px))
    cx, cy = (b[0]+b[2])/2, (b[1]+b[3])/2
    cx += rng.uniform(-.16, .16)*side
    cy += rng.uniform(-.16, .16)*side
    x, y = int(cx-side/2), int(cy-side/2)
    side = int(round(side))
    canvas = np.full((side, side, 3), 114, np.uint8)
    x1, y1, x2, y2 = max(0, x), max(0, y), min(w, x+side), min(h, y+side)
    if x2 <= x1 or y2 <= y1:
        return None, []
    canvas[y1-y:y2-y, x1-x:x2-x] = frame[y1:y2, x1:x2]
    labels = []
    for a in boxes:
        bx1, by1 = max(a[0], x), max(a[1], y)
        bx2, by2 = min(a[2], x+side), min(a[3], y+side)
        visible = max(0, bx2-bx1)*max(0, by2-by1)
        if visible/max(1, (a[2]-a[0])*(a[3]-a[1])) < .6:
            continue
        if min(bx2-bx1, by2-by1)*320/side < 2:
            continue
        labels.append([0, ((bx1+bx2)/2-x)/side, ((by1+by2)/2-y)/side,
                       (bx2-bx1)/side, (by2-by1)/side])
    canvas = cv2.resize(canvas, (320, 320), interpolation=cv2.INTER_AREA)
    if rng.random() < .3:
        canvas = cv2.GaussianBlur(canvas, (3, 3), rng.uniform(.3, .9))
    return canvas, labels


def mined_negative(frame, boxes, rng):
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([140, 45, 55], np.uint8), np.array([179, 255, 255], np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates = [r for r in stats[1:] if 4 <= r[4] < w*h*.2 and min(r[2], r[3]) >= 2]
    rng.shuffle(candidates)
    for bx, by, bw, bh, _ in candidates[:30]:
        side = max(96, min(640, 4*max(bw, bh)))
        x, y = int(max(0, min(w-side, bx+bw/2-side/2))), int(max(0, min(h-side, by+bh/2-side/2)))
        x2, y2 = min(w, x+side), min(h, y+side)
        if any(min(x2, a[2]) > max(x, a[0]) and min(y2, a[3]) > max(y, a[1]) for a in boxes):
            continue
        roi = frame[y:y2, x:x2]
        if roi.size:
            return cv2.resize(roi, (320, 320), interpolation=cv2.INTER_AREA)
    return None


def save_view(root, split, name, image, labels):
    cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(root/'images'/split/(name+'.jpg')))
    text = '\n'.join(' '.join(str(v) for v in line) for line in labels)
    (root/'labels'/split/(name+'.txt')).write_text(text+'\n' if text else '', encoding='ascii')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--train-views', type=int, default=2)
    p.add_argument('--max-negatives', type=int, default=500)
    args = p.parse_args()
    cv2.setNumThreads(2)
    rng = random.Random(2400)
    out = args.output.resolve()
    if (out/'data.yaml').exists():
        raise ValueError('Use a new output directory; do not overwrite a dataset')
    records, originals, counts, source_ids = [], {}, {}, {}
    for split in ('train', 'val', 'test'):
        for sub in ('images', 'labels'):
            (out/sub/split).mkdir(parents=True, exist_ok=True)
        files = sorted((args.source/'images'/split).glob('*.jpg'))
        if not files:
            raise ValueError('source split missing: '+split)
        originals[split] = len(files)
        source_ids[split] = {f.stem for f in files}
        counts[split] = dict(originals=len(files), roi_views=0, negative_views=0)
        for f in files:
            label = args.source/'labels'/split/(f.stem+'.txt')
            shutil.copy2(f, out/'images'/split/f.name)
            shutil.copy2(label, out/'labels'/split/label.name)
            if split == 'test':
                continue
            frame = read_image(f)
            if frame is None:
                raise ValueError('image unreadable: '+str(f))
            boxes = boxes_for(label, frame.shape)
            views = args.train_views if split == 'train' else 1
            for v in range(views):
                if not boxes:
                    continue
                image, labels = crop_view(frame, boxes, rng.randrange(len(boxes)), rng)
                if image is None or not labels:
                    continue
                name = f.stem+'_roi_%02d'%v
                save_view(out, split, name, image, labels)
                counts[split]['roi_views'] += 1
                records.append(dict(name=name, source_id=f.stem, split=split, kind='context_scale_crop'))
            if split == 'train' and counts[split]['negative_views'] < args.max_negatives:
                image = mined_negative(frame, boxes, rng)
                if image is not None:
                    name = f.stem+'_negative'
                    save_view(out, split, name, image, [])
                    counts[split]['negative_views'] += 1
                    records.append(dict(name=name, source_id=f.stem, split=split, kind='pink_non_balloon_patch'))
    if source_ids['train'] & (source_ids['val'] | source_ids['test']) or source_ids['val'] & source_ids['test']:
        raise ValueError('original source-image leakage')
    source = json.loads((args.source/'dataset_source.json').read_text(encoding='utf-8'))
    report = dict(source_dataset=source, seed=2400, original_images=originals, views=counts,
                  augmentation_records=records, validation_test_images_in_training=False,
                  real_100m_images=0, limitation='Scale/context augmentation, not measured-distance field data')
    (out/'dataset_source.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (out/'data.yaml').write_text(yaml.safe_dump(dict(path=str(out), train='images/train', val='images/val',
                                                     test='images/test', names={0:'balloon'})), encoding='utf-8')
    print(json.dumps(dict(original_images=originals, views=counts, real_100m_images=0)), flush=True)


if __name__ == '__main__':
    main()
