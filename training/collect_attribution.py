"""Keep original author/license/landing-page metadata for the exact Open Images subset."""
import argparse,csv,io,json,urllib.request
from pathlib import Path
URL='https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('dataset',type=Path);args=parser.parse_args()
    source=json.loads((args.dataset/'dataset_source.json').read_text(encoding='utf-8'))
    wanted={x['image_id'] for x in source['images']};found=[]
    with urllib.request.urlopen(URL,timeout=60) as response:
        for row in csv.DictReader(io.TextIOWrapper(response,encoding='utf-8')):
            if row['ImageID'] in wanted:
                row['LocalChanges']='Resized to <=960 pixels; JPEG quality 90; YOLO boxes converted from official annotations.'
                found.append(row)
    target=args.dataset/'image_attribution.csv'
    with target.open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=sorted({k for r in found for k in r}));writer.writeheader();writer.writerows(found)
    missing=sorted(wanted-{r['ImageID'] for r in found})
    (args.dataset/'attribution_source.json').write_text(json.dumps(dict(source_url=URL,found=len(found),missing=missing),indent=2),encoding='utf-8')
    print('Attribution records:',len(found),'missing:',len(missing),flush=True)
    if missing:raise RuntimeError('Missing image attribution records')
if __name__=='__main__':main()
