from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from .images import validate_box

Text = Annotated[str, Field(min_length=1, max_length=3000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Highlight(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=100)]
    box: list[int] = Field(min_length=4, max_length=4)
    origin: Literal["model", "author"] = "model"

    @field_validator("box", mode="before")
    @classmethod
    def valid_box(cls, value):
        validate_box(value)
        return value


class Step(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")] = "step-1"
    photo_id: str = ""
    operator_note: str = Field(default="", max_length=3000)
    title: str = Field(default="", max_length=120)
    instruction: str = Field(default="", max_length=3000)
    completion_check: str = Field(default="", max_length=500)
    highlights: list[Highlight] = Field(default_factory=list, max_length=8)
    missing_information: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=8)
    reviewed: bool = False


class CreateGuide(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    goal: str = Field(default="", max_length=1000)
    language: Literal["en", "ko"] = "ko"


class SaveGuide(CreateGuide):
    version: int = Field(ge=1)
    steps: list[Step] | None = Field(default=None, max_length=6)
    # Accept the original single-step request while old tabs refresh.
    step: Step | None = None

    @model_validator(mode="after")
    def unique_steps(self):
        if (self.steps is None) == (self.step is None):
            raise ValueError("Provide either steps or the legacy step field.")
        steps = self.steps if self.steps is not None else [self.step]
        if len({s.id for s in steps}) != len(steps):
            raise ValueError("Step IDs must be unique.")
        return self

    def ordered_steps(self):
        return [s.model_dump() for s in (self.steps if self.steps is not None else [self.step])]


class Version(StrictModel):
    version: int = Field(ge=1)


class Login(StrictModel):
    password: str = Field(min_length=1, max_length=200)


class GeneratedStep(StrictModel):
    photo_id: str
    title: Annotated[str, Field(min_length=1, max_length=120)]
    instruction: Text
    completion_check: Annotated[str, Field(min_length=1, max_length=500)]
    highlights: list[Highlight] = Field(max_length=8)
    missing_information: list[Annotated[str, Field(max_length=300)]] = Field(max_length=8)


class AskQuestion(StrictModel):
    step_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    question: Annotated[str, Field(min_length=1, max_length=1000)]
    clarification_of: Annotated[str, Field(min_length=20, max_length=64)] | None = None
    recheck_of: Annotated[str, Field(min_length=20, max_length=64)] | None = None
    selection_id: Annotated[str, Field(min_length=20, max_length=64)] | None = None
    intent: Literal["auto", "procedure", "appearance"] = "procedure"

    @model_validator(mode="after")
    def separate_followups(self):
        if self.recheck_of and self.clarification_of:
            raise ValueError("Recheck and clarification are separate followups.")
        return self


class ResolveGap(StrictModel):
    resolved: StrictBool


class PhotoPoint(StrictModel):
    x: Annotated[StrictInt, Field(ge=0, le=1000)]
    y: Annotated[StrictInt, Field(ge=0, le=1000)]


class SelectObject(StrictModel):
    step_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    point: PhotoPoint


class AnswerEvidence(StrictModel):
    source: Literal["photo", "instruction", "completion_check"]
    detail: Annotated[str, Field(min_length=1, max_length=500)]


class GroundedAnswer(StrictModel):
    status: Literal["answered", "needs_clarification", "not_visible", "insufficient_information"]
    answer: Annotated[str, Field(min_length=1, max_length=4000)]
    clarification_options: list[Annotated[str, Field(min_length=1, max_length=150)]] = Field(max_length=4)
    highlights: list[Highlight] = Field(max_length=4)
    evidence: list[AnswerEvidence] = Field(max_length=6)

    @model_validator(mode="after")
    def consistent_answer(self):
        if self.status == "answered" and not self.evidence:
            raise ValueError("An answer needs evidence.")
        if self.status != "needs_clarification" and self.clarification_options:
            raise ValueError("Only clarification can have options.")
        if self.status != "answered" and (self.highlights or self.evidence):
            raise ValueError("An unresolved question cannot assert evidence or a box.")
        if any(h.origin != "model" for h in self.highlights):
            raise ValueError("Answer highlights must be model observations.")
        if self.highlights and not any(e.source == "photo" for e in self.evidence):
            raise ValueError("A location needs photo evidence.")
        return self


def question_response_schema(intent):
    """Export state constraints using Meta's supported nested-anyOf subset.

    Runtime model validators are not represented by model_json_schema(). The
    wire-only result wrapper permits a union below a plain object root; it is
    unwrapped before runtime validation and never changes our public API shape.
    """
    base = GroundedAnswer.model_json_schema()
    highlight = base['$defs']['Highlight']
    highlight['properties']['origin'] = {'type':'string','enum':['model']}
    highlight['properties']['box']['items'] = {'type':'integer','minimum':0,'maximum':1000}
    highlight['required'] = list(highlight['properties'])
    for definition in base['$defs'].values():
        if definition.get('type') == 'object':
            definition['required'] = list(definition['properties'])

    states = []
    for status in ('answered','needs_clarification','not_visible','insufficient_information'):
        props = deepcopy(base['properties'])
        props['status'] = {'type':'string','enum':[status]}
        if status != 'needs_clarification':
            props['clarification_options']['maxItems'] = 0
        if status == 'answered':
            props['evidence']['minItems'] = 1
            evidence = deepcopy(base['$defs']['AnswerEvidence'])
            evidence['properties']['source']['enum'] = (['photo'] if intent == 'appearance'
                                                       else ['instruction','completion_check'])
            props['evidence']['items'] = evidence
            if intent == 'procedure':props['highlights']['maxItems'] = 0
        else:
            props['evidence']['maxItems'] = 0
            props['highlights']['maxItems'] = 0
        states.append({'type':'object','properties':props,'required':list(props),'additionalProperties':False})
    return {'type':'object','properties':{'result':{'anyOf':states}},
            'required':['result'],'additionalProperties':False,'$defs':base['$defs']}
