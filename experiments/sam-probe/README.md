# SAM 3.1 도입 후보 검증

2026년 11월 2일. 서비스에 아직 연결하지 않은 기술 검증입니다.

실제 API 4회: 노란 트레이 1개·윤곽, 실제 사진의 검은 펜 1개·윤곽, 없는 빨간 가위 0개, 선택 지점의 검은 펜 1개·윤곽. 응답 시간 2.232~6.163초. API 상태·반환 위치·마스크 존재를 확인하고 브라우저에서 윤곽을 살폈습니다. 4회로 일반 정확도나 사용자 효과를 주장하지 않습니다.

결과는 summary.json, 실제 응답은 로컬 state/evidence/sam-probe/에 있습니다. [서비스 연동 전 검증 화면](sam-probe.html)에서 원본 사진의 윤곽과 사각형을 각각 끄고 켤 수 있습니다. 이후 제품에 연결한 결과는 [물체 선택 검증 기록](../../docs/SELECTION_RESULTS.md)에 있습니다.

재현하려면 requirements-eval.txt를 설치하고 scripts/probe_sam.py를 실행합니다. 기본값은 호출 계획만 표시하며, --execute를 붙일 때만 API 4회를 호출합니다. 공식 Python 파서 meta-sam-parser 0.1.0으로 응답을 해석합니다. 화면용 HTML은 이번 실험에서 저장한 응답을 렌더링한 자료입니다.

채택 기준: 물체를 가리키는 질문이 쉬워지고 작은 물체 강조가 명확해지는가? 추가 지연이 허용되는가? 없거나 모호한 대상에서 잘못 강조하지 않는가? 실패 시 사각형 안내·승인 설명을 계속 볼 수 있는가? 네 가지를 확인한 뒤 제품에 연결합니다.

출처: https://dev.meta.ai/docs/sam/overview, https://dev.meta.ai/docs/sam/segmenting, https://dev.meta.ai/docs/sam/client-libraries.
