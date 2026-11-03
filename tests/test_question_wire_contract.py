"""The schema sent to Meta must express the invariants enforced after generation."""
import copy
import json
import os
import unittest
from unittest.mock import Mock,patch
import jsonschema
import test_app
from showme.vision import answer_question,VisionError

class QuestionWireTests(unittest.TestCase):
    def setUp(self):
        self.step={'id':'step-1','title':'펜','instruction':'검은 펜은 서명용입니다.',
                   'completion_check':'잉크가 마른 뒤 건넵니다.','highlights':[]}
        self.value={'status':'answered','answer':'검은 펜은 서명용입니다.','clarification_options':[],
                    'highlights':[],'evidence':[{'source':'instruction','detail':self.step['instruction']}]}

    def wire(self,intent='procedure'):
        value=copy.deepcopy(self.value)
        if intent=='appearance':value['evidence']=[{'source':'photo','detail':'검은 펜이 보입니다.'}]
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'result':value})}}]}
        with patch('showme.vision.requests.post',return_value=response) as post,patch.dict(os.environ,{'MODEL_API_KEY':'fixture-key'}):
            answer_question(b'fixture',self.step,'펜 질문',[],intent=intent)
        return post.call_args.kwargs['json']['response_format']['json_schema']['schema']

    def test_advertised_question_schema_rejects_self_contradictions(self):
        schema=self.wire();validator=jsonschema.Draft202012Validator(schema)
        self.assertTrue(validator.is_valid({"result":self.value}))
        invalid=[]
        v=copy.deepcopy(self.value);v['evidence']=[];invalid.append(v)
        v=copy.deepcopy(self.value);v['clarification_options']=['검은 펜'];invalid.append(v)
        for status in ['not_visible','insufficient_information','needs_clarification']:
            v=copy.deepcopy(self.value);v['status']=status;invalid.append(v)
        v=copy.deepcopy(self.value);v['highlights']=[{'box':[1,1,10,10],'label':'펜','origin':'model'}];invalid.append(v)
        v=copy.deepcopy(self.value);v['evidence']=[{'source':'photo','detail':'검은 펜'}];invalid.append(v)
        for v in invalid:
            with self.subTest(status=v['status'],evidence=v['evidence'],options=v['clarification_options']):
                self.assertFalse(validator.is_valid({"result":v}))
        for status in ['not_visible','insufficient_information','needs_clarification']:
            v=copy.deepcopy(self.value);v.update(status=status,evidence=[],highlights=[])
            if status=='needs_clarification':v['clarification_options']=['검은 펜','파란 펜']
            self.assertTrue(validator.is_valid({"result":v}))

    def test_visual_schema_requires_photo_evidence_and_model_geometry(self):
        validator=jsonschema.Draft202012Validator(self.wire('appearance'))
        self.assertFalse(validator.is_valid({"result":self.value}))
        v=copy.deepcopy(self.value);v['evidence']=[{'source':'photo','detail':'검은 펜'}]
        self.assertTrue(validator.is_valid({"result":v}))
        v['highlights']=[{'label':'펜','box':[0,1,10,10],'origin':'author'}]
        self.assertFalse(validator.is_valid({"result":v}))

    def test_schema_stays_in_metas_supported_strict_subset(self):
        schema=self.wire()
        self.assertEqual(schema['type'],'object')
        self.assertNotIn('anyOf',schema)
        def visit(node):
            if isinstance(node,dict):
                self.assertNotIn('allOf',node);self.assertNotIn('oneOf',node)
                if node.get('type')=='object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']),set(node['properties']))
                for value in node.values():visit(value)
            elif isinstance(node,list):
                for value in node:visit(value)
        visit(schema)

    def test_diagnostics_distinguish_failure_stages_without_input_or_exception_objects(self):
        bad=copy.deepcopy(self.value);bad['clarification_options']=['PRIVATE-DO-NOT-LOG']
        bodies=[({'choices':[{'finish_reason':'length','message':{'content':'SECRET-CONTENT'}}]},'finish_reason'),
                ({'choices':[{'finish_reason':'stop','message':{'content':'SECRET-CONTENT'}}]},'json'),
                ({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'result':bad})}}]},'consistency')]
        for body,stage in bodies:
            response=Mock(status_code=200);response.json.return_value=body
            with patch('showme.vision.requests.post',return_value=response),patch.dict(os.environ,{'MODEL_API_KEY':'fixture-key'}):
                with self.assertRaises(VisionError) as caught:answer_question(b'private-photo',self.step,'private-question',[])
            diagnostics=caught.exception.diagnostics
            self.assertEqual(diagnostics['stage'],stage)
            serialized=json.dumps(diagnostics)
            for secret in ['SECRET-CONTENT','PRIVATE-DO-NOT-LOG','private-photo','private-question','fixture-key']:
                self.assertNotIn(secret,serialized)

if __name__=='__main__':unittest.main()
