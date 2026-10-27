"""Convert the official Matterport balloon VIA polygons to YOLO boxes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from PIL import Image
import yaml

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path(__file__).parent/"downloads/balloon_dataset.zip")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent/"datasets/balloon")
    args = parser.parse_args()
    output = args.output.resolve()
    # Read the ZIP directly: no extraction of untrusted paths.
    counts, hashes = {}, {"train": set(), "val": set()}
    with zipfile.ZipFile(args.archive) as archive:
        names = archive.namelist()
        for split in ("train", "val"):
            annotation = next(name for name in names if name.endswith(split+"/via_region_data.json"))
            records = json.loads(archive.read(annotation)).values()
            image_dir, label_dir = output/"images"/split, output/"labels"/split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            count = 0
            for record in records:
                filename = Path(record["filename"]).name
                member = annotation.rsplit("/", 1)[0]+"/"+filename
                raw = archive.read(member)
                hashes[split].add(hashlib.sha256(raw).hexdigest())
                image = image_dir/filename
                image.write_bytes(raw)
                with Image.open(image) as im:
                    width, height = im.size
                regions = record.get("regions", [])
                if isinstance(regions, dict):
                    regions = regions.values()
                boxes = []
                for region in regions:
                    shape = region["shape_attributes"]
                    xs, ys = shape["all_points_x"], shape["all_points_y"]
                    left, right = max(0, min(xs)), min(width, max(xs))
                    top, bottom = max(0, min(ys)), min(height, max(ys))
                    if right > left and bottom > top:
                        boxes.append("0 %.8f %.8f %.8f %.8f" % (
                            (left+right)/2/width, (top+bottom)/2/height,
                            (right-left)/width, (bottom-top)/height))
                (label_dir/(Path(filename).stem+".txt")).write_text("\n".join(boxes)+"\n", encoding="utf-8")
                count += 1
            counts[split] = count
    if hashes["train"] & hashes["val"]:
        raise ValueError("train/validation image overlap")
    data = {"path": str(output), "train": "images/train", "val": "images/val", "nc": 1, "names": ["balloon"]}
    (output/"data.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    (output/"dataset_source.json").write_text(json.dumps({
        "source": "Matterport Mask_RCNN balloon dataset",
        "url": "https://github.com/matterport/Mask_RCNN/releases/download/v2.1/balloon_dataset.zip",
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "images": counts, "train_val_overlap": False,
        "limitation": "Public starter data; boat/water/camera-specific validation and negative scenes are required."
    }, indent=2), encoding="utf-8")
    print(json.dumps(counts))
    print(output/"data.yaml")

if __name__ == "__main__":
    main()
