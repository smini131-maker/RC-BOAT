"""Portable archives of the existing splits, without caches or duplicate originals."""
import argparse,hashlib,json,zipfile
from pathlib import Path
def main():
    parser=argparse.ArgumentParser();parser.add_argument('dataset',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);manifest={}
    for split in ('train','val','test'):
        groups=[[]];size=0
        for image in sorted((args.dataset/'images'/split).glob('*.jpg')):
            if size+image.stat().st_size>80*1024*1024 and groups[-1]:groups.append([]);size=0
            groups[-1].extend([image,args.dataset/'labels'/split/(image.stem+'.txt')]);size+=image.stat().st_size
        for index,files in enumerate(groups,1):
            suffix=('_part%d'%index) if len(groups)>1 else ''
            target=args.output/('openimages_balloon_'+split+suffix+'.zip')
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
                for path in files:archive.write(path,path.relative_to(args.dataset))
            manifest[target.name]=dict(bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    target=args.output/'openimages_balloon_metadata.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('data.yaml','train: images/train\nval: images/val\ntest: images/test\nnames:\n  0: balloon\n')
        for name in ('dataset_source.json','image_attribution.csv','attribution_source.json'):archive.write(args.dataset/name,name)
        archive.writestr('README.txt','Extract every dataset archive into one folder (train parts, val, test and metadata). data.yaml must sit next to images/ and labels/.\nImages are resized/reencoded derivatives; original authors, source links and licenses are retained in image_attribution.csv.\nSplit groups use perceptual hashes. Public images are not the actual competition camera/course.\n')
    manifest[target.name]=dict(bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (args.output/'dataset_export_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
