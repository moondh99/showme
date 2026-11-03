"""Contract/guard regressions. Frozen evaluation phrases are deliberately absent."""
import json,unittest
from unittest.mock import patch
import test_app
from showme.reasoning import PlannedAnswer,AuditDecision,answer_with_reasoning
from showme.models import GroundedAnswer,AnswerEvidence
from showme.vision import VisionError

class SemanticReasoningTests(unittest.TestCase):
    def setUp(self):
        self.step={'id':'step-1','title':'시험 안내','instruction':'초록 표는 열람용입니다. 빨간 표는 반출용입니다.',
                   'completion_check':'반출은 승인 확인 뒤에만 가능합니다.','highlights':[]}
    def plan(self,decision='policy',target='초록 표',quote='초록 표는 열람용입니다.',intent='procedure',conditions=None):
        return PlannedAnswer(status='answered',answer='임의 문장',clarification_options=[],highlights=[],
            evidence=[{'source':'instruction','detail':quote}],intent=intent,
            assessment={'decision':decision,'target':target,'conditions':conditions or []})
    def test_audit_replaces_wrong_target_even_with_valid_quote(self):
        first=self.plan('allowed','초록 표','빨간 표는 반출용입니다.')
        final=self.plan('blocked','초록 표')
        with patch('showme.reasoning.request_structured',side_effect=[(first,{'usage':{'total_tokens':5}}),(final,{'usage':{'total_tokens':7}})]) as req:
            answer,metrics=answer_with_reasoning(b'photo',self.step,'이 표의 반출 권한을 확인해 주세요.',[],intent='auto',audit_policy='full')
        self.assertEqual(metrics['assessment']['decision'],'blocked')
        self.assertEqual(metrics['assessment']['target'],'초록 표')
        self.assertEqual(metrics['usage']['total_tokens'],12)
        self.assertTrue(metrics['audit_changed']);self.assertEqual(req.call_count,2)
        self.assertNotIn('빨간',answer['answer'])
    def test_scope_is_model_resolved_and_not_keyword_locked(self):
        photo=self.plan();photo.intent='appearance';photo.assessment.decision='visual';photo.evidence=[AnswerEvidence(source='photo',detail='초록 표가 보입니다.')]
        with patch('showme.reasoning.request_structured',side_effect=[(photo,{}),(photo,{})]):
            answer,metrics=answer_with_reasoning(b'photo',self.step,'열람에 사용하는 표의 윤곽은요?',[],intent='auto',audit_policy='full')
        self.assertEqual(metrics['resolved_intent'],'appearance')
    def test_condition_quotes_are_included_and_unknown_cannot_be_allowed(self):
        p=self.plan('allowed','빨간 표','빨간 표는 반출용입니다.',conditions=[{'source':'completion_check','detail':self.step['completion_check'],'state':'unknown'}])
        with patch('showme.reasoning.request_structured',side_effect=[(p,{}),(p,{})]):
            answer,m=answer_with_reasoning(b'photo',self.step,'승인 상태가 불명확해요.',[],intent='procedure',audit_policy='full')
        self.assertEqual(m['assessment']['decision'],'conditional')
        self.assertIn(self.step['completion_check'],answer['answer'])
    def test_forged_condition_and_audit_failure_do_not_escape_as_answer(self):
        p=self.plan(conditions=[{'source':'completion_check','detail':'이 내용은 승인되지 않았습니다.','state':'met'}])
        with patch('showme.reasoning.request_structured',side_effect=[(p,{}),(p,{})]):
            with self.assertRaises(VisionError):answer_with_reasoning(b'photo',self.step,'규칙을 확인해 주세요.',[],intent='procedure',audit_policy='full')
        with patch('showme.reasoning.request_structured',side_effect=[(self.plan(),{}),VisionError('timeout','검토 실패')]):
            with self.assertRaises(VisionError):answer_with_reasoning(b'photo',self.step,'규칙을 확인해 주세요.',[],intent='auto',audit_policy='full')
    def test_allowed_without_any_permission_basis_stays_conditional(self):
        p=self.plan('allowed')
        with patch('showme.reasoning.request_structured',side_effect=[(p,{}),(p,{})]):
            answer,m=answer_with_reasoning(b'photo',self.step,'판정을 확인해 주세요.',[],intent='procedure',audit_policy='full')
        self.assertEqual(m['assessment']['decision'],'conditional')

    def test_other_target_never_supplies_a_permission_condition(self):
        related={'source':'completion_check','detail':self.step['completion_check'],'state':'met','role':'other_target'}
        p=self.plan('allowed',conditions=[related])
        with patch('showme.reasoning.request_structured',return_value=(p,{})):
            answer,metrics=answer_with_reasoning(b'photo',self.step,'판정을 확인해 주세요.',[])
        self.assertEqual(metrics['assessment']['decision'],'conditional')
        self.assertEqual(metrics['assessment']['conditions'],[related])
        self.assertNotIn(related['detail'],answer['answer'])

    def test_reason_fragment_remains_in_context_with_its_exception(self):
        self.step['instruction']='초록 표는 반출할 수 없습니다. 다만 담당자 승인 후 가능합니다.'
        rule={'source':'instruction','detail':'초록 표는 반출할 수 없습니다.','state':'met','role':'basis'}
        p=self.plan('blocked',quote=rule['detail'],conditions=[rule])
        with patch('showme.reasoning.request_structured',return_value=(p,{})):
            answer,metrics=answer_with_reasoning(b'photo',self.step,'반출해도 되나요?',[])
        self.assertEqual(metrics['assessment']['conditions'][0]['role'],'condition')
        self.assertEqual(answer['answer'],self.step['instruction'])

    def test_runtime_also_rejects_incoherent_semantic_metadata(self):
        from pydantic import ValidationError
        base=self.plan().model_dump()
        bad=[]
        value=json.loads(json.dumps(base));value['assessment']['decision']='visual';bad.append(value)
        value=json.loads(json.dumps(base));value['intent']='appearance';bad.append(value)
        value=json.loads(json.dumps(base));value['assessment']['target']='';bad.append(value)
        for value in bad:
            with self.assertRaises(ValidationError):PlannedAnswer.model_validate(value)

    def test_auto_wire_schema_rejects_scope_evidence_mismatch(self):
        import jsonschema
        from showme.reasoning import plan_schema
        schema=plan_schema('auto');validator=jsonschema.Draft202012Validator(schema)
        value=self.plan().model_dump()
        self.assertTrue(validator.is_valid({'result':value}))
        value['intent']='appearance';value['assessment']['decision']='visual'
        self.assertFalse(validator.is_valid({'result':value}))
        value['evidence']=[{'source':'photo','detail':'초록 표'}]
        self.assertTrue(validator.is_valid({'result':value}))

    def test_explicit_photo_scope_does_not_receive_approved_rules(self):
        p=self.plan();p.intent='appearance';p.assessment.decision='visual';p.evidence=[AnswerEvidence(source='photo',detail='초록 표')]
        with patch('showme.reasoning.request_structured',return_value=(p,{})) as req:
            answer_with_reasoning(b'photo',self.step,'무슨 모양인가요?',[],intent='appearance',audit_policy='full')
        context=json.loads(req.call_args.args[1][0]['text'])
        self.assertEqual(context['approved_step'],{'id':'step-1'})
        self.assertEqual(req.call_count,1)


class SemanticApiTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    guide_with_photo=test_app.AppTests.guide_with_photo
    save=test_app.AppTests.save
    generated=test_app.AppTests.generated
    approve=test_app.AppTests.approve

    def test_default_api_uses_semantic_scope_despite_a_procedural_keyword(self):
        from fastapi.testclient import TestClient
        from showme.app import create_app
        d,pub=self.approve(self.generated())
        p=PlannedAnswer(status='answered',answer='검은 펜의 윤곽입니다.',clarification_options=[],highlights=[],
            evidence=[{'source':'photo','detail':'검은 펜이 보입니다.'}],intent='appearance',
            assessment={'decision':'visual','target':'검은 펜','conditions':[]})
        with patch('showme.reasoning.request_structured',side_effect=[(p,{'model':'fixture-only'}),(p,{'model':'fixture-only'})]) as req:
            with TestClient(create_app(self.temp.name,author_password='test-password')) as c:
                r=c.post('/api/learn/'+pub['share_id']+'/questions',json={
                    'step_id':'step-1','question':'원고에 사용하는 필기구의 윤곽을 알려주세요.','intent':'auto'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['intent'],'appearance')
        self.assertEqual(r.json()['assessment']['decision'],'visual')
        self.assertEqual(r.json()['approved_context'],[])
        self.assertEqual(req.call_count,2)
        with self.app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT intent FROM question_turns WHERE id=?',(r.json()['id'],)).fetchone()[0],'appearance')

if __name__=='__main__':unittest.main()
