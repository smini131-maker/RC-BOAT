"""Compare old and new ONNX models on the held-out red subset using the ROS detector."""
import argparse
import json
import random
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from prepare_small_objects import boxes_for, read_image
from prepare_red_balloon import expose, negative_crop

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'catkin_ws/src/rcboat_ros/src'))
from rcboat_ros.balloon_tracking import TargetTracker, validate_config
from rcboat_ros.balloon_detector import BalloonDetector


def iou(a, b):
    area = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area)


def counts(detections, expected):
    unmatched = list(expected)
    hits = 0
    confirmed = sorted((d for d in detections if d['pink_confirmed']),
                       key=lambda d: -d['confidence'])
    for detection in confirmed:
        if unmatched:
            index = max(range(len(unmatched)), key=lambda i: iou(detection['bbox'], unmatched[i]))
            if iou(detection['bbox'], unmatched[index]) >= .5:
                unmatched.pop(index)
                hits += 1
    return hits, len(confirmed)


def evaluate(detector, dataset, records, reference, split='test', max_background=100):
    report = {k:dict(frames=0, expected_boxes=0, matched_boxes=0, confirmed_boxes=0)
              for k in ('original','bright','dim','background','reference_non_balloon')}
    rng = random.Random(2460)
    def measure(frame, boxes, condition):
        detector.reset_search()
        detections = detector.detect(frame)
        matched, confirmed = counts(detections, boxes)
        row = report[condition]
        row['frames'] += 1
        row['expected_boxes'] += len(boxes)
        row['matched_boxes'] += matched
        row['confirmed_boxes'] += confirmed

    for photo in sorted((dataset/'images'/split).glob('*.jpg')):
        record = records.get(photo.stem)
        if not record and report['background']['frames'] >= max_background:
            continue
        frame = read_image(photo)
        boxes = boxes_for(dataset/'labels'/split/(photo.stem+'.txt'), frame.shape)
        if record:
            expected = [boxes[i] for i in record['red_boxes']]
            measure(frame, expected, 'original')
            for condition in ('bright','dim'):
                measure(expose(frame,rng,condition), expected, condition)
        if report['background']['frames'] < max_background:
            crop = negative_crop(frame, boxes, rng)
            if crop is not None:
                measure(crop, [], 'background')
    if reference:
        original = read_image(reference)
        if original is None:
            raise ValueError('reference image unreadable: '+str(reference))
        reference_rng = random.Random(2460)
        frames = [(name, original if name=='original' else expose(original,reference_rng,name))
                  for name in ('original','bright','dim')]
        for _, frame in frames:
            measure(frame, [], 'reference_non_balloon')
        report['reference_roi_sequence'] = {}
        detector.config['long_range_enabled'] = True
        for name, frame in frames:
            detector.reset_search()
            tracker = TargetTracker()
            height, width = frame.shape[:2]
            confirmed = acquired = 0
            for i in range(12):
                detections = detector.detect(frame)
                confirmed += sum(d['pink_confirmed'] for d in detections)
                acquired += int(tracker.update(detections,width,height,100+i/12,detector.config)['acquired'])
            report['reference_roi_sequence'][name] = dict(frames=12, confirmed_boxes=confirmed, acquired_frames=acquired)
        detector.config['long_range_enabled'] = False
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','baseline','baseline-manifest','candidate','candidate-manifest','report'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    records = json.loads((args.dataset/'dataset_source.json').read_text(encoding='utf-8'))['red_candidate_records']
    output = dict(scope='same red filter for both models, full-frame inference at 320',
                  matching_iou=.5, score_threshold=.35,
                  ground_truth='red proxy from HSV screening of original Open Images balloon boxes',
                  background='red crops outside known balloon boxes; some objects may be unlabelled',
                  lighting='synthetic exposure of held-out real photos',
                  competition_field_test=False, model_sha256={})
    with TemporaryDirectory() as temporary:
        for name, path, manifest in (('baseline',args.baseline,args.baseline_manifest),
                                     ('candidate',args.candidate,args.candidate_manifest)):
            meta = json.loads(manifest.read_text(encoding='utf-8'))
            output['model_sha256'][name] = meta['sha256']
            meta['target_colour'] = 'red'
            comparison = Path(temporary)/(name+'.json')
            comparison.write_text(json.dumps(meta),encoding='utf-8')
            config = validate_config(dict(model_path=str(path),model_manifest=str(comparison),
                                         backend='onnxruntime',long_range_enabled=False))
            detector = BalloonDetector(config)
            try:
                output[name] = evaluate(detector,args.dataset,records,args.reference)
            finally:
                detector.close()
    args.report.write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    main()
