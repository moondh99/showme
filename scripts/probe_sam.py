#!/usr/bin/env python3
"""Four paid SAM capability probes. Install requirements-eval.txt first."""
import argparse,asyncio,base64,json,os,sys,time
from dataclasses import asdict
from pathlib import Path
import requests
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from meta_sam_parser import parse_responses_stream,image_segmentation_format,SegmentationBoxRecord,SegmentationMaskRecord,decode_mask_to_raster,decode_mask_to_svg_path,PromptObject,FramePrompt,PromptPoint,build_object_prompt
from showme.images import prepare_image
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if not args.execute:
        print('Dry run: 4 SAM 3.1 requests. Add --execute to spend API credits.')
        return
    os.chdir(ROOT)
    load_dotenv(ROOT/'.env.local',override=False)
    cases=[('yellow_tray','public/demo/reception-setup/03-badge-trays.png','yellow tray'),('real_black_pen','experiments/meta-vision/inputs/notepad.jpg','black pen'),('no_red_scissors','public/demo/reception-setup/02-signing-tools.png','red scissors'),('point_black_pen','public/demo/reception-setup/02-signing-tools.png',None)]
    root=Path('state/evidence/sam-probe');root.mkdir(exist_ok=True);summary=[]
    for id,path,prompt in cases:
     image,data=prepare_image(Path(path));width,height=image.size
     if prompt is None:prompt=build_object_prompt(size=(width,height),objects=[PromptObject(id=1,prompts=[FramePrompt(points=[PromptPoint(int(width*.744),int(height*.54))])])])
     payload={'model':'sam-3.1','input':[{'type':'message','role':'user','content':[{'type':'input_text','text':prompt},{'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(data).decode()}]}],'stream':True,'metadata':{'mask_encoding':'one_bit'}}
     start=time.monotonic();row={'case':id,'image':path,'prompt':prompt,'source_size':[width,height]}
     try:
      events=[]
      with requests.post('https://api.meta.ai/v1/responses',headers={'Authorization':'Bearer '+os.environ['MODEL_API_KEY'],'Accept':'text/event-stream'},json=payload,stream=True,timeout=(10,90),allow_redirects=False) as r:
       row['http_status']=r.status_code
       if r.status_code!=200:raise ValueError('upstream HTTP '+str(r.status_code))
       for line in r.iter_lines():
        if line.startswith(b'data: '):
         value=line[6:]
         if value!=b'[DONE]':events.append(json.loads(value))
      async def parse():
       async def source():
        for event in events:yield event
       parser=parse_responses_stream(source(),image_segmentation_format());return await parser.final_result()
      result=asyncio.run(parse());boxes=[];masks=[]
      for record in result.records:
       if isinstance(record,SegmentationBoxRecord):boxes.append({'object_id':record.object_id,'box':[record.left,record.top,record.right,record.bottom]})
       if isinstance(record,SegmentationMaskRecord):
        raster=decode_mask_to_raster(record.mask);pathdata=decode_mask_to_svg_path(record.mask)
        masks.append({'object_id':record.object_id,'foreground_pixels':sum(raster),'raster_size':len(raster),'svg_path_length':len(pathdata)})
        (root/(id+'-'+record.object_id+'-mask-path.txt')).write_text(pathdata)
      (root/(id+'-events.json')).write_text(json.dumps(events))
      row.update(boxes=boxes,masks=masks,outcome=asdict(result.outcome))
     except Exception as exc:row['error']=type(exc).__name__+': '+str(exc)[:200]
     row['elapsed_seconds']=round(time.monotonic()-start,3);summary.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
     (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
