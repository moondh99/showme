"""Transport effort/timing and fail-closed contracts; no paid requests."""
import json,os,unittest
from unittest.mock import Mock,patch
import test_app
from showme.reasoning import PlannedAnswer,AuditDecision,answer_with_reasoning
from showme.vision import request_structured,VisionError


class EffortTests(unittest.TestCase):
    def setUp(self):
        self.step={'id':'step-1','title':'시험','instruction':'초록 표는 열람용입니다.','completion_check':'승인 뒤에만 반출합니다.','highlights':[]}
        self.plan=PlannedAnswer(status='answered',answer='승인 문구',clarification_options=[],highlights=[],
            evidence=[{'source':'instruction','detail':self.step['instruction']}],intent='procedure',
            assessment={'decision':'blocked','target':'초록 표','conditions':[]})

    def test_transport_sends_effort_and_separates_http_from_local_work(self):
        response=Mock(status_code=200)
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'result':self.plan.model_dump()})}}],
            'usage':{'completion_tokens':110,'completion_tokens_details':{'reasoning_tokens':90}}}
        with patch('showme.vision.requests.post',return_value=response) as post,patch.dict(os.environ,{'MODEL_API_KEY':'fixture'}):
            _,m=request_structured('prompt',[],PlannedAnswer,'ShowMeSemanticPlan',response_key='result',reasoning_effort='low')
        self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'low')
        self.assertEqual(m['reasoning_effort'],'low')
        self.assertEqual(set(m['timings']),{'prepare_seconds','http_seconds','decode_validate_seconds'})
        self.assertEqual(m['reasoning_tokens'],90)
        self.assertEqual(m['visible_output_tokens'],20)

    def test_corrective_effort_retains_independent_correction_in_two_calls(self):
        with patch('showme.reasoning.request_structured',side_effect=[(self.plan,{}),(self.plan,{})]) as call:
            _,m=answer_with_reasoning(b'photo',self.step,'선택한 표로 반출할까요?',[],intent='auto')
        self.assertEqual([c.kwargs.get('reasoning_effort') for c in call.call_args_list],['low','low'])
        self.assertEqual(m['effort_profile'],'corrective')
        self.assertEqual(m['model_calls'],2)

    def test_legacy_comparison_omits_effort_and_invalid_profile_never_calls(self):
        with patch('showme.reasoning.request_structured',side_effect=[(self.plan,{}),(AuditDecision(verdict='accept',reason='none'),{})]) as call:
            answer_with_reasoning(b'photo',self.step,'반출할까요?',[],intent='auto',effort_profile='legacy')
        self.assertTrue(all(c.kwargs.get('reasoning_effort') is None for c in call.call_args_list))
        with patch('showme.reasoning.request_structured') as call:
            with self.assertRaises(ValueError):answer_with_reasoning(b'photo',self.step,'반출할까요?',[],effort_profile='unsafe')
        call.assert_not_called()

    def test_public_question_cannot_override_internal_profile(self):
        from pydantic import ValidationError
        from showme.models import AskQuestion
        with self.assertRaises(ValidationError):
            AskQuestion.model_validate({'step_id':'step-1','question':'이건 무엇인가요?', 'effort_profile':'legacy'})

    def test_low_effort_truncation_is_not_retried_or_returned(self):
        response=Mock(status_code=200);response.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'PRIVATE'}}]}
        with patch('showme.vision.requests.post',return_value=response) as post,patch.dict(os.environ,{'MODEL_API_KEY':'fixture'}):
            with self.assertRaises(VisionError) as error:
                request_structured('prompt',[],PlannedAnswer,'ShowMeSemanticPlan',reasoning_effort='low')
        self.assertEqual(error.exception.diagnostics['stage'],'finish_reason')
        self.assertEqual(post.call_count,1)

if __name__=='__main__':unittest.main()
