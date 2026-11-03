"""Small, deterministic boundaries around question intent and approved excerpts."""
import re

# Ambiguous questions stay on the approved-text path. A descriptive noun such
# as '파란색 펜' is not a request for visual information. Only explicit visual
# predicates opt into photo-only context; this is not a semantic classifier.
OPERATIONAL = re.compile(r"무슨\s*일|하는\s*일|의미|뜻|상징|정해|정한|담당|업무|기준|규정|구분|전용|역할|누구|언제|필요|용인가|용이|서명|참가자|현장등록|사전등록|사용|용도|쓰(?:나요|는|면|며|고|려|기|지|자|세요)|쓸|써(?:도|야|서|요|\?|$)|방법|절차|규칙|순서|준비|배치|놓[아는을기]|둬|두어|건네|꺼내|교체|받아도|해도|돼|되나요|되나|해야|허용|금지|가능|괜찮|구매|브랜드|시작|종료|몇\s*시")
VISUAL = re.compile(
    r"(?:무슨|어떤)\s*색|색(?:깔)?(?:은|는|이)\s*(?:뭐|무엇|어떤|어떻|알려)|"
    r"색(?:깔)?(?:과|,).*?(?:알려|보여)|색(?:깔)?\s*(?:알려|보여)|"
    r"색(?:깔)?(?:인가|이야|이에요|입니까)|모양|형태|위치|생겼|보이|보여|보이나|"
    r"(?:왼쪽|오른쪽|왼편|오른편|좌측|우측)(?:에는|에|엔)?\s*(?:뭐|무엇|어떤|있)|"
    r"어디(?:에|쯤)?\s*(?:있|보)|(?:정체|이름)(?:은|이|을|이야|인가)|"
    r"(?:이건|이게|이것은|이\s*물체는|선택한\s*물체는)\s*(?:뭐|무엇)(?:예요|인가|이야|이죠|죠)"
)
CONTEXT_DEPENDENT = re.compile(r"(?:^|[\n.!?。]\s*)(?:단(?:,|\s)|다만|하지만|그러나|그렇지|또한|그리고|이때|그때)|경우|조건|예외|제외|한해|한하여|할\s*때|일\s*때|아니면|않으면|없으면|있으면|전까지|이후|먼저|다음|앞서|위의|해당")


def operational_question(question):
    return bool(OPERATIONAL.search(question))


def question_intent(question):
    return "appearance" if VISUAL.search(question) and not operational_question(question) else "procedure"


def approved_excerpt(text, quote):
    """Return only complete source sentences, conservatively retaining context.

    A repeated fragment or a detected dependency/exception retains the full field.
    This deliberately cannot prove that every possible condition was recognized.
    The interface always exposes the full approved field beside the excerpt.
    """
    if text.count(quote) != 1 or CONTEXT_DEPENDENT.search(text):
        return text
    start = text.index(quote)
    end = start + len(quote)
    boundaries = list(re.finditer(r"(?<=[.!?。])\s+|\n+", text))
    left = max((m.end() for m in boundaries if m.end() <= start), default=0)
    right = next((m.start() for m in boundaries if m.start() >= end), len(text))
    return text[left:right].strip()


def approved_context(step, status, intent):
    """Always accompany an operational answer with both complete approved fields.

    Unlike excerpt heuristics this cannot drop an unrecognized prohibition or a
    restriction in completion_check. Build it on the server, never from model prose.
    """
    if status != "answered" or intent != "procedure":
        return []
    return [{"source": source, "text": step[source]}
            for source in ("instruction", "completion_check")]
