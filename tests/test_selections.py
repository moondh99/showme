"""Selection contracts use fixture SAM output; real calls are recorded separately."""
import copy
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import test_app as fixtures
from test_questions import answered, clarification
from showme.app import create_app
from showme.segmentation import pixel_point, segment_object
from showme.store import Store
from showme.vision import VisionError, answer_question


def fixture_segmenter(data, metadata, point):
    return {'status':'selected','point':point,'box':[0,0,1000,1000],
            'mask_bounds':[0,0,metadata['width'],metadata['height']],
            'mask_path':f"M0 0L{metadata['width']} 0L{metadata['width']} {metadata['height']}L0 {metadata['height']}Z",
            'photo_width':metadata['width'],'photo_height':metadata['height']}, {'model':'fixture-SAM-not-real-API'}


class SelectionTests(unittest.TestCase):
    setUp=fixtures.AppTests.setUp
    tearDown=fixtures.AppTests.tearDown
    guide_with_photo=fixtures.AppTests.guide_with_photo
    save=fixtures.AppTests.save
    generated=fixtures.AppTests.generated
    approve=fixtures.AppTests.approve

    def ready(self,segmenter=fixture_segmenter,answerer=None,two_steps=False):
        draft=self.generated()
        if two_steps:
            other=copy.deepcopy(draft['steps'][0]);other['id']='step-2';other['instruction']='다른 단계의 규칙';draft['steps'].append(other);draft=self.save(draft).json()
            for step in draft['steps']:step['reviewed']=True
            draft=self.save(draft).json()
            pub=self.client.post('/api/guides/'+draft['id']+'/publish',json={'version':draft['version']}).json()
        else:draft,pub=self.approve(draft)
        app=create_app(self.temp.name,author_password='test-password',segmenter=segmenter,
                       answerer=answerer or (lambda data,step,q,history,selection=None:(answered(step),{})))
        client=TestClient(app);self.addCleanup(client.close)
        return draft,pub,client,app

    def select(self,client,pub,point=None,step='step-1'):
        return client.post('/api/learn/'+pub['share_id']+'/selections',json={'step_id':step,'point':point or {'x':500,'y':500}})

    def ask(self,client,pub,selection,question='이건 무엇에 쓰나요?',step='step-1',parent=None):
        return client.post('/api/learn/'+pub['share_id']+'/questions',json={'step_id':step,'question':question,'selection_id':selection,'clarification_of':parent})

    def test_selected_question_uses_approved_step_not_draft_and_never_changes_snapshot(self):
        observed=[]
        def answer(data,step,q,history,selection):
            observed.append((step,selection));return answered(step),{}
        draft,pub,client,app=self.ready(answerer=answer)
        public=client.get('/api/learn/'+pub['share_id']).json();draft['steps'][0]['instruction']='미승인 변경';draft['steps'][0]['operator_note']='비공개 메모';self.save(draft)
        selected=self.select(client,pub)
        self.assertEqual(selected.status_code,200,selected.text);selected=selected.json()
        self.assertEqual(selected['status'],'selected');self.assertNotIn('metrics',selected)
        response=self.ask(client,pub,selected['id'])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['selection_id'],selected['id'])
        step,selection=observed[0]
        self.assertNotIn('operator_note',step);self.assertEqual(step['instruction'],public['steps'][0]['instruction'])
        self.assertEqual(selection['point'],{'x':500,'y':500})
        self.assertEqual(client.get('/api/learn/'+pub['share_id']).json(),public)

    def test_coordinates_and_extra_mask_fields_rejected_before_model(self):
        calls=[]
        def segment(*args):calls.append(1);return fixture_segmenter(*args)
        draft,pub,client,app=self.ready(segmenter=segment)
        for point in [{'x':-1,'y':500},{'x':1001,'y':500},{'x':True,'y':500},{'x':500.1,'y':500},{'x':'500','y':500}]:
            self.assertEqual(self.select(client,pub,point).status_code,422)
        r=client.post('/api/learn/'+pub['share_id']+'/selections',json={'step_id':'step-1','point':{'x':500,'y':500},'mask_path':'M0 0Z'})
        self.assertEqual(r.status_code,422);self.assertEqual(calls,[])

    def test_selection_is_bound_to_revision_step_and_photo(self):
        draft,pub,client,app=self.ready(two_steps=True)
        selected=self.select(client,pub).json()
        self.assertEqual(self.ask(client,pub,selected['id'],step='step-2').status_code,404)
        otherdraft,otherpub=self.approve(self.generated())
        self.assertEqual(self.ask(client,otherpub,selected['id']).status_code,404)
        self.assertEqual(self.ask(client,pub,'unissued-selection-token-with-length').status_code,404)
        self.assertEqual(self.select(client,pub,step='not-in-this-revision').status_code,404)

    def test_expiry_and_restart(self):
        draft,pub,client,app=self.ready();selected=self.select(client,pub).json()
        restarted=TestClient(create_app(self.temp.name,author_password='test-password',answerer=lambda data,step,q,h,s:(answered(step),{})))
        self.addCleanup(restarted.close)
        self.assertEqual(self.ask(restarted,pub,selected['id']).status_code,200)
        with app.state.store.connect() as db:db.execute('UPDATE selections SET created_at=? WHERE id=?',(time.time()-86401,selected['id']))
        self.assertEqual(self.ask(restarted,pub,selected['id']).status_code,404)

    def test_clarification_cannot_silently_change_selected_object(self):
        count=[]
        def answer(data,step,q,history,selection):count.append(1);return clarification(),{}
        draft,pub,client,app=self.ready(answerer=answer)
        first=self.select(client,pub).json()['id'];parent=self.ask(client,pub,first).json()['id']
        second=self.select(client,pub,{'x':600,'y':500}).json()['id']
        self.assertEqual(self.ask(client,pub,second,parent=parent).status_code,404)
        self.assertEqual(self.ask(client,pub,None,parent=parent).status_code,404)
        self.assertEqual(len(count),1)
        self.assertEqual(self.ask(client,pub,first,parent=parent).status_code,200)

    def test_selected_answer_without_approved_quote_is_refused(self):
        def photo_only(*args):return {'status':'answered','answer':'운영자용입니다.','clarification_options':[],
            'highlights':[],'evidence':[{'source':'photo','detail':'사진에 펜이 보인다.'}]},{}
        draft,pub,client,app=self.ready(answerer=photo_only);selected=self.select(client,pub).json()['id'];r=self.ask(client,pub,selected)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'insufficient_information')
        self.assertIn('모르겠습니다',r.json()['answer']);self.assertEqual(r.json()['evidence'],[])

    def test_invalid_path_dimensions_and_box_are_not_persisted(self):
        bad=[]
        for field,value in [('mask_path','M0 0\"/><script>bad</script>'),('photo_width',999),('mask_bounds',[0,0,10,10]),('box',[0,0,900,900])]:
            def broken(data,meta,point,field=field,value=value):
                s,m=fixture_segmenter(data,meta,point);s[field]=value;return s,m
            bad.append(broken)
        draft,pub,client,app=self.ready(segmenter=lambda *args:bad.pop(0)(*args))
        for _ in range(4):self.assertEqual(self.select(client,pub).status_code,502)
        with app.state.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM selections').fetchone()[0],0)

    def test_not_found_timeout_and_shared_rate_limit(self):
        def no_match(data,meta,point):return {'status':'not_found','point':point},{}
        draft,pub,client,app=self.ready(segmenter=no_match)
        r=self.select(client,pub);self.assertEqual(r.status_code,200);self.assertNotIn('id',r.json())
        for _ in range(9):self.assertEqual(self.ask(client,pub,None).status_code,200)
        self.assertEqual(self.select(client,pub).status_code,429)
        state=[]
        def timeout_then_valid(*args):
            if not state:state.append(True);raise VisionError('timeout','시간 초과')
            return fixture_segmenter(*args)
        app=create_app(self.temp.name,author_password='test-password',segmenter=timeout_then_valid)
        with TestClient(app) as retry:
            self.assertEqual(self.select(retry,pub).status_code,502)
            self.assertEqual(self.select(retry,pub).status_code,200)

    def test_existing_eight_column_question_table_migrates_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            with sqlite3.connect(Path(directory)/'showme.sqlite3') as db:
                db.execute('CREATE TABLE question_turns(id TEXT PRIMARY KEY,share_id TEXT,step_id TEXT,parent_id TEXT,question TEXT,answer TEXT,metrics TEXT,created_at REAL)')
                db.execute('INSERT INTO question_turns VALUES(?,?,?,?,?,?,?,?)',('old','share','step',None,'old question','old answer','{}',1))
            store=Store(directory)
            with store.connect() as db:
                row=db.execute('SELECT * FROM question_turns').fetchone()
                self.assertEqual(row['answer'],'old answer');self.assertIsNone(row['selection_id'])

    def test_real_sam_wire_fixture_uses_pixels_and_validates_mask(self):
        events=json.loads((Path(__file__).parent/'fixtures/sam_point_events.json').read_text())
        response=MagicMock(status_code=200);response.__enter__.return_value=response
        response.iter_lines.return_value=[b'data: '+json.dumps(e).encode() for e in events]
        with patch('showme.segmentation.requests.post',return_value=response) as post,patch.dict('os.environ',{'MODEL_API_KEY':'fixture-key'}):
            selected,metrics=segment_object(b'canonical-photo',{'width':1536,'height':1024},{'x':744,'y':540})
        self.assertEqual(selected['mask_bounds'],[1105,346,1187,766]);self.assertEqual(selected['status'],'selected')
        self.assertTrue(selected['mask_path']);self.assertEqual(metrics['model'],'sam-3.1')
        payload=post.call_args.kwargs['json'];self.assertEqual(payload['input'][0]['content'][0]['text'],'<0f>1<|point;x=1142;y=552;w=1536;h=1024|>')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertEqual(pixel_point({'x':1000,'y':1000},1536,1024),(1535,1023))

    def test_mask_geometry_only_is_sent_to_answer_model(self):
        step={'id':'step','title':'펜','instruction':'검은 펜은 서명용입니다.','completion_check':'펜 확인','highlights':[]}
        selection={'point':{'x':744,'y':540},'box':[719,337,773,749],'mask_path':'PRIVATE-HUGE-PATH','id':'server-private-token'}
        response=MagicMock(status_code=200);response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({"result":answered(step)})}}]}
        with patch('showme.vision.requests.post',return_value=response) as post,patch.dict('os.environ',{'MODEL_API_KEY':'fixture-key'}):
            result,metrics=answer_question(b'canonical',step,'이건?',[],selection)
        content=json.loads(post.call_args.kwargs['json']['messages'][1]['content'][0]['text'])
        self.assertEqual(content['selected_object'],{'point':selection['point'],'box':selection['box']})
        self.assertNotIn('PRIVATE',json.dumps(content));self.assertNotIn('server-private-token',json.dumps(content))
        self.assertEqual(result['highlights'],[])

if __name__=='__main__':unittest.main()
