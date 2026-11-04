"""Reproducible Matterport boxes + pink-colour augmentation, split by source image."""
import argparse,hashlib,json,zipfile
from pathlib import Path
import cv2
import numpy as np
import yaml

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--archive',type=Path,default=Path(__file__).parent/'downloads/balloon_dataset.zip')
    ap.add_argument('--output',type=Path,default=Path(__file__).parent/'datasets/balloon');args=ap.parse_args()
    root=args.output.resolve();counts={};hashes={}
    with zipfile.ZipFile(args.archive) as z:
        for split in ('train','val'):
            meta=next(n for n in z.namelist() if n.endswith(split+'/via_region_data.json'))
            records=json.loads(z.read(meta));hashes[split]=set();counts[split]=0
            for record in records.values():
                name=Path(record['filename']).name
                raw=z.read(meta.rsplit('/',1)[0]+'/'+name);hashes[split].add(hashlib.sha256(raw).hexdigest())
                frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);h,w=frame.shape[:2]
                regions=record['regions'];regions=regions.values() if isinstance(regions,dict) else regions
                boxes=[];mask=np.zeros((h,w),np.uint8)
                for region in regions:
                    a=region['shape_attributes'];xs=a['all_points_x'];ys=a['all_points_y']
                    x1,x2=max(0,min(xs)),min(w,max(xs));y1,y2=max(0,min(ys)),min(h,max(ys))
                    if x2<=x1 or y2<=y1:continue
                    boxes.append('0 %.8f %.8f %.8f %.8f'%((x1+x2)/2/w,(y1+y2)/2/h,(x2-x1)/w,(y2-y1)/h))
                    cv2.fillPoly(mask,[np.array(list(zip(xs,ys)),np.int32)],255)
                for dest,stem,img in [(split,Path(name).stem,frame)]:
                    for sub in ('images','labels'):(root/sub/dest).mkdir(parents=True,exist_ok=True)
                    cv2.imencode('.jpg',img)[1].tofile(str(root/'images'/dest/(stem+'.jpg')))
                    (root/'labels'/dest/(stem+'.txt')).write_text('\n'.join(boxes)+'\n')
                # Preserve highlights/texture; change only annotated balloon pixels.
                hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);fg=mask>0
                hsv[:,:,0][fg]=165;hsv[:,:,1][fg]=np.maximum(hsv[:,:,1][fg],90)
                pink=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
                dest='train' if split=='train' else 'pink_validation'
                for sub in ('images','labels'):(root/sub/dest).mkdir(parents=True,exist_ok=True)
                stem=Path(name).stem+'_pink'
                cv2.imencode('.jpg',pink)[1].tofile(str(root/'images'/dest/(stem+'.jpg')))
                (root/'labels'/dest/(stem+'.txt')).write_text('\n'.join(boxes)+'\n')
                counts[split]+=1
    if hashes['train'] & hashes['val']:raise ValueError('source-image split leakage')
    data=dict(path=str(root),train='images/train',val='images/val',names={0:'balloon'})
    (root/'data.yaml').write_text(yaml.safe_dump(data),encoding='utf-8')
    source=dict(source='Matterport Mask_RCNN balloon dataset',url='https://github.com/matterport/Mask_RCNN/releases/download/v2.1/balloon_dataset.zip',
        sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),original_images=counts,
        training_augmentation='annotated balloon colour shifted to pink; highlights retained',source_image_overlap=False,
        pink_validation='recoloured held-out validation; not an independent competition test')
    (root/'dataset_source.json').write_text(json.dumps(source,indent=2),encoding='utf-8')
    print(json.dumps(source))

if __name__=='__main__':main()
