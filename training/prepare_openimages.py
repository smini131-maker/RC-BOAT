"""Download all physical-balloon examples from official Open Images annotations.

The small per-class CSV is produced by scanning the official annotation URL.
No class IDs, images or labels are invented. Split is grouped by perceptual hash.
"""
import argparse,csv,hashlib,json,math,random,time,urllib.request,shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import cv2,numpy as np,yaml

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    rows=defaultdict(list)
    for r in csv.DictReader(args.source.open()):
        if r['IsDepiction']=='0' and r['IsGroupOf']=='0' and (float(r['XMax'])-float(r['XMin']))*(float(r['YMax'])-float(r['YMin']))>.0002:rows[r['ImageID']].append(r)
    out=args.output.resolve();cache=out/'originals';cache.mkdir(parents=True,exist_ok=True)
    results=[];failures=[]
    def fetch(item):
        image_id,boxes=item;path=cache/(image_id+'.jpg')
        cached=path.exists()
        if cached:raw=path.read_bytes()
        else:
            url='https://open-images-dataset.s3.amazonaws.com/train/'+image_id+'.jpg'
            request=urllib.request.Request(url,headers={'User-Agent':'RCBoatBalloonResearch/2.3'})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(request,timeout=25) as r:raw=r.read(16000000)
                    break
                except Exception:
                    if attempt==2:raise
                    time.sleep(.5*(attempt+1))
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        if image is None:raise ValueError('invalid JPEG '+image_id)
        gray=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(9,8));bits=(gray[:,1:]>gray[:,:-1]).flatten()
        phash=sum(int(v)<<i for i,v in enumerate(bits))
        if not cached:
            scale=min(1,960/max(image.shape[:2]));image=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale)))
            cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,90])[1].tofile(str(path))
        return image_id,boxes,phash,hashlib.sha256(path.read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures={pool.submit(fetch,item):item[0] for item in sorted(rows.items())}
        for i,f in enumerate(as_completed(futures),1):
            try:results.append(f.result())
            except Exception as exc:failures.append(dict(id=futures[f],error=str(exc)))
            if i%50==0:print('downloaded',i,'/',len(futures),'successful',len(results),flush=True)
    results.sort();buckets=defaultdict(list);parent={r[0]:r[0] for r in results}
    def find(x):
        while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    for image_id,boxes,phash,sha in results:
        close=[]
        for band in range(4):
            for other_hash,other_id in buckets[(band,(phash>>(16*band))&65535)]:
                if (phash^other_hash).bit_count()<=4:union(image_id,other_id)
        for band in range(4):buckets[(band,(phash>>(16*band))&65535)].append((phash,image_id))
    # Rebuilding splits must never leave a former training image in validation.
    # Only our generated image/label trees under the explicitly chosen output are removed.
    for sub in ('images','labels'):
        generated=(out/sub).resolve()
        if generated.parent!=out or generated.name not in ('images','labels'):raise ValueError('unsafe output')
        if generated.exists():shutil.rmtree(generated)
    counts=defaultdict(int);box_counts=defaultdict(int);manifest=[]
    for image_id,boxes,phash,sha in results:
        value=int(hashlib.sha256(('rcboat-v230-'+find(image_id)).encode()).hexdigest()[:8],16)%100
        split='train' if value<80 else 'val' if value<90 else 'test'
        for sub in ('images','labels'):(out/sub/split).mkdir(parents=True,exist_ok=True)
        image=(cache/(image_id+'.jpg')).read_bytes();(out/'images'/split/(image_id+'.jpg')).write_bytes(image)
        labels=[]
        for r in boxes:
            x1,x2,y1,y2=[float(r[k]) for k in ('XMin','XMax','YMin','YMax')]
            labels.append('0 %.8f %.8f %.8f %.8f'%((x1+x2)/2,(y1+y2)/2,x2-x1,y2-y1))
        (out/'labels'/split/(image_id+'.txt')).write_text('\n'.join(labels)+'\n')
        counts[split]+=1;box_counts[split]+=len(labels)
        manifest.append(dict(image_id=image_id,source='Open Images V6',image_sha256=sha,split=split,perceptual_group=find(image_id)))
    data=dict(path=str(out),train='images/train',val='images/val',test='images/test',names={0:'balloon'})
    (out/'data.yaml').write_text(yaml.safe_dump(data),encoding='utf-8')
    source=dict(dataset='Open Images V6 physical Balloon class',class_id='/m/01j51',
        annotations_url='https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv',
        images_url='https://open-images-dataset.s3.amazonaws.com/train/{ImageID}.jpg',
        split_method='80/10/10 deterministic split grouped by image perceptual hash; no augmentation counted as new originals',
        original_images=dict(counts),balloon_boxes=dict(box_counts),download_failures=failures,images=manifest,
        image_license_source='https://storage.googleapis.com/openimages/web/factsfigures.html',
        limitation='Public photos, not the actual competition camera or marine course.')
    (out/'dataset_source.json').write_text(json.dumps(source,indent=2),encoding='utf-8')
    print('FINAL',dict(counts),dict(box_counts),'failures',len(failures),flush=True)

if __name__=='__main__':main()
