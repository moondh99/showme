"""Call-budget and fail-closed contracts for R12. No paid requests."""
import unittest
from unittest.mock import patch
import test_app
from showme.reasoning import PlannedAnswer,AuditDecision,answer_with_reasoning,compact_audit_schema
from showme.vision import VisionError


def visual():
    return PlannedAnswer(status='answered',answer='동그란 물체입니다.',clarification_options=[],highlights=[],
        evidence=[{'source':'photo','detail':'둥근 윤곽이 보입니다.'}],intent='appearance',
        assessment={'decision':'visual','target':'물체','conditions':[]})

class LatencyPolicyTests(unittest.TestCase):
    def test_plain_visual_request_does_not_repeat_the_model_call(self):
        step={'id':'step-1','title':'도구','instruction':'표는 열람용입니다.','completion_check':'표 확인','highlights':[]}
        with patch('showme.reasoning.request_structured',return_value=(visual(),{})) as request:
            _,metrics=answer_with_reasoning(b'photo',step,'물체의 윤곽은 어떤가요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(request.call_count,1)
        self.assertEqual(metrics['model_calls'],1)


    def setUp(self):
        self.step={'id':'step-1','title':'도구','instruction':'표는 열람용입니다.','completion_check':'승인 뒤에만 반출합니다.','highlights':[]}

    def rule(self,decision='blocked'):
        return PlannedAnswer(status='answered',answer='임의 문장',clarification_options=[],highlights=[],
            evidence=[{'source':'instruction','detail':self.step['instruction']}],intent='procedure',
            assessment={'decision':decision,'target':'표','conditions':[]})

    def test_operation_word_in_visual_request_retains_review_without_forcing_scope(self):
        with patch('showme.reasoning.request_structured',side_effect=[(visual(),{}),(AuditDecision(verdict='accept',reason='none'),{})]) as request:
            _,m=answer_with_reasoning(b'photo',self.step,'열람에 사용하는 물체의 윤곽은요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(request.call_count,2)
        self.assertEqual(m['resolved_intent'],'appearance')
        self.assertEqual(m['review_reason'],'operating_language')

    def test_operational_claim_in_visual_draft_is_not_returned_unreviewed(self):
        unsafe=visual();unsafe.answer='이 표는 사용이 가능합니다.'
        with patch('showme.reasoning.request_structured',side_effect=[
                (unsafe,{}),(AuditDecision(verdict='repair',reason='unsafe_permission'),{}),
                (self.rule('blocked'),{})]) as request:
            _,m=answer_with_reasoning(b'photo',self.step,'모양을 보여 주세요.',[],intent='auto',effort_profile='bounded')
        self.assertEqual(request.call_count,3)
        self.assertEqual(m['assessment']['decision'],'blocked')
        self.assertEqual(m['review_reason'],'operating_language')

    def test_selected_target_followup_and_refusal_do_not_skip_review(self):
        missing=visual().model_dump();missing.update(status='insufficient_information',evidence=[],highlights=[],
            assessment={'decision':'unknown','target':'물체','conditions':[]})
        for plan,history,selection in [(visual(),[],{'point':{'x':5,'y':5},'box':[0,0,10,10]}),
                (visual(),[{'question':'원래 질문','response':{}}],None),
                (PlannedAnswer.model_validate(missing),[],None)]:
            with patch('showme.reasoning.request_structured',side_effect=[(plan,{}),(AuditDecision(verdict='accept',reason='none'),{})]) as request:
                _,m=answer_with_reasoning(b'photo',self.step,'윤곽을 알려 주세요.',history,selection,intent='auto',effort_profile='bounded')
            self.assertEqual(request.call_count,2)
            self.assertEqual(m['audit_strategy'],'compact')

    def test_every_operational_decision_keeps_audit(self):
        for decision in ['policy','allowed','blocked','conditional']:
            with patch('showme.reasoning.request_structured',side_effect=[(self.rule(decision),{}),(AuditDecision(verdict='accept',reason='none'),{})]) as request:
                _,m=answer_with_reasoning(b'photo',self.step,'표를 확인해 주세요.',[],intent='auto',effort_profile='bounded')
            self.assertEqual(request.call_count,2)
            self.assertEqual(m['audit_strategy'],'compact')

    def test_replacement_is_used_and_failed_review_never_returns_draft(self):
        first=self.rule('allowed');fixed=self.rule('blocked')
        with patch('showme.reasoning.request_structured',side_effect=[(first,{}),(AuditDecision(verdict='repair',reason='wrong_target'),{}),(fixed,{})]):
            _,m=answer_with_reasoning(b'photo',self.step,'반출해도 되나요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(m['assessment']['decision'],'blocked')
        with patch('showme.reasoning.request_structured',side_effect=[(first,{}),VisionError('timeout','검토 실패')]) as request:
            with self.assertRaises(VisionError) as caught:answer_with_reasoning(b'photo',self.step,'반출해도 되나요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(request.call_count,2)
        self.assertEqual(caught.exception.diagnostics['model_calls'],2)

    def test_repair_failure_is_bounded_at_three_calls(self):
        with patch('showme.reasoning.request_structured',side_effect=[
                (self.rule('allowed'),{}),(AuditDecision(verdict='repair',reason='unsafe_permission'),{}),
                VisionError('timeout','교정 실패')]) as request:
            with self.assertRaises(VisionError) as caught:
                answer_with_reasoning(b'photo',self.step,'반출해도 되나요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(request.call_count,3)
        self.assertEqual(caught.exception.diagnostics['model_calls'],3)

    def test_accepted_plan_still_has_literal_quotes_and_permission_limits(self):
        for state,expected in [('unknown','conditional'),('not_met','blocked')]:
            value=self.rule('allowed').model_dump()
            value['assessment']['conditions']=[{'source':'completion_check','detail':self.step['completion_check'],'state':state}]
            plan=PlannedAnswer.model_validate(value)
            with patch('showme.reasoning.request_structured',side_effect=[(plan,{}),(AuditDecision(verdict='accept',reason='none'),{})]):
                answer,m=answer_with_reasoning(b'photo',self.step,'반출할까요?',[],intent='auto',effort_profile='bounded')
            self.assertEqual(m['assessment']['decision'],expected)
            self.assertIn(self.step['completion_check'],answer['answer'])
        value=self.rule('allowed').model_dump();value['assessment']['conditions']=[{'source':'completion_check','detail':'승인되지 않은 문장','state':'met'}]
        plan=PlannedAnswer.model_validate(value)
        with patch('showme.reasoning.request_structured',side_effect=[(plan,{}),(AuditDecision(verdict='accept',reason='none'),{})]):
            with self.assertRaises(VisionError) as caught:answer_with_reasoning(b'photo',self.step,'반출할까요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(caught.exception.diagnostics['model_calls'],2)

    def test_repair_usage_counts_every_successful_pass(self):
        with patch('showme.reasoning.request_structured',side_effect=[
                (self.rule('allowed'),{'usage':{'total_tokens':5},'elapsed_seconds':2}),
                (AuditDecision(verdict='repair',reason='wrong_target'),{'usage':{'total_tokens':3},'elapsed_seconds':1}),
                (self.rule('blocked'),{'usage':{'total_tokens':7},'elapsed_seconds':3})]):
            _,m=answer_with_reasoning(b'photo',self.step,'반출할까요?',[],intent='auto',effort_profile='bounded')
        self.assertEqual(m['model_calls'],3)
        self.assertEqual(m['usage']['total_tokens'],15)
        self.assertEqual(m['elapsed_seconds'],6)

    def test_compact_schema_and_runtime_reject_inconsistent_verdicts(self):
        import jsonschema
        from pydantic import ValidationError
        schema=compact_audit_schema('auto');validator=jsonschema.Draft202012Validator(schema)
        self.assertTrue(validator.is_valid({'result':{'verdict':'accept','reason':'none'}}))
        value={'verdict':'repair','reason':'condition_logic'}
        self.assertTrue(validator.is_valid({'result':value}))
        value['verdict']='accept'
        self.assertFalse(validator.is_valid({'result':value}))
        with self.assertRaises(ValidationError):AuditDecision.model_validate(value)

if __name__=='__main__':unittest.main()
