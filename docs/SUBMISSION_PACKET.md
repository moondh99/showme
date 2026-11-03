# ShowMe 제출 자료 초안 — 2026년 11월 3일

공식 [참가자 안내](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details#7-submission-process-15)와 로그인 후 [실제 제출 폼](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit)을 읽어 항목을 확인했다. 폼에 입력·저장·제출하거나 홍보 동의란을 선택하지 않았다. 공개 GitHub 저장소와 접근 가능한 3분 영상이 필요하다. 마감은 **한국 시간 2026년 11월 5일 11:00**, 공식 표기 11월 4일 21:00 EST다.

## 폼에 맞춘 입력 초안

팀 이름·기여자 명단·참가 트랙·설문 답변·홍보 동의는 실제 참가 정보와 사용자 의사로 정한다. 아래 영문은 편집 가능한 원고이며 글자 수 제한이나 언어 제한이 없다고 보장하지 않는다. 프로젝트 이름은 ShowMe다. 문제 분야는 현재 구현을 기준으로 **Build for Your World**가 맞는다. Indie/Startups 참가 트랙과 문제 분야는 별도 항목이다.

### Project Description

ShowMe helps a new worker ask about an object they can see but cannot name. They point to an object in an approved task photograph, then ask what it is for or whether a proposed action follows the task rules.

A supervisor supplies the operating notes, reviews the AI-generated instructions and highlights, and publishes an immutable guide. The learner selects an object with SAM 3.1. Muse Spark connects that selection to the current step's approved instructions and evaluates the relevant target and conditions. Each operational answer shows the full approved source text, with the cited passages marked. Ambiguous targets trigger clarification; missing information remains unresolved instead of becoming an invented rule.

Our demo starts with two similar tags. A learner points to the blue storage tag and says they have completed training and intend to borrow equipment. ShowMe displays the storage tag’s prohibition at the top and labels the training or supervisor condition as a rule for the other tag. A second scene demonstrates that editing a draft leaves an earlier approved guide unchanged.

This is a working MVP with automated checks and internal live-API tests. The demo photographs are AI-staged. We have not yet established reductions in worker time or mistakes through external user testing.

### Describe your use of Meta products to build the submitted project

We use the Meta Model API for Muse Spark 1.3 and SAM 3.1. Muse Spark generates draft step instructions, completion checks, and highlights from task photos and supervisor notes. The supervisor reviews these before publication.

SAM 3.1 segments the object at the learner's selected point in the approved photograph. Muse Spark then interprets the selected target and the proposed action against the current step's approved instructions. Operational questions use a separate semantic review that can correct the initial assessment. The server validates structured responses, checks cited text against the approved source, and binds selections and questions to the correct guide revision, step, and photo.

The interface distinguishes AI interpretation from approved source text. Meta models provide visual grounding and target/condition reasoning; the application enforces approval, source-text integrity, permissions, request limits, and immutable publication.

### Why are Meta's models important to your solution?

The learner often cannot describe the object precisely enough for a text query. SAM 3.1 turns a point in a task photograph into a selected object. Muse Spark uses the photograph, that selection, and the approved text to interpret what the learner means and whether the relevant rules apply.

The useful interaction requires both object selection and rule reasoning: recognizing a blue tag leaves open which rule governs it and whether a prerequisite belongs to a different tag. Our application keeps supervisor approval and source validation around the model's interpretation. This lets the demo show an inspectable target-and-rule decision while preserving the full approved wording and its conditions.

### Provide feedback from your experience using partner technologies

팀의 실제 경험으로 작성할 항목이다. 현재 기록에서 Baseten·Modal·Fireworks를 제품 추론에 사용한 이력은 확인하지 못했다. 사용했다고 기재하지 않으며 Meta API 자체에 관한 의견과 구별한다.

## 행사 중 개발한 범위와 자료 출처

시연에서 구별해 말할 신규 구현: 다단계 사진 안내서 작성·검토·승인, 승인본과 초안 분리, 직접 선택과 SAM 윤곽, 선택 대상·조건을 확인하는 질문 응답, 승인 원문 검증과 전체 문맥 표시, 모호성 확인·유보, 질문 보완 목록과 검색, 요청 한도 및 접근 경계, 데스크톱·모바일 작업 화면. 커밋 기록과 해당 소스로 확인하고 최종 영상에서 실제 보여준 범위만 주장한다.

Muse Spark와 SAM 모델 자체를 개발했다고 말하지 않는다. 시연 사진 4장은 내장 이미지 생성 도구로 제작했다. 생성 모델이 Meta Muse Image라는 근거는 없으므로 Meta 이미지 생성 기능으로 소개하지 않는다. 샘플 노트 사진은 Eric Bailey의 CC0 공개 사진이며 `public/demo/sample-photo-source.json`에 출처와 해시가 있다. 기존 의존성·라이브러리와 외부 모델은 직접 구현한 기능과 구별한다.

## 제출 전 남은 실제 산출물

| 항목 | 현재 상태 | 완료 기준 |
| --- | --- | --- |
| 공개 GitHub | 미완료, 이 저장소에 remote 없음 | 공개할 계정과 저장소 확정 후 비밀·로컬 데이터 제외, 새 복제에서 실행 확인 |
| 3분 영상 | 대본 준비, 촬영·업로드 미완료 | 실제 결과로 녹화·편집, 로그아웃 상태에서 영상 링크 열기 |
| 외부 체험 | 사용자 요청으로 배포 보류 | 호스팅 대상·영속 저장소·HTTPS 확정 후 배포, 외부 접근과 재시작 보존 확인 |
| 행사 중 기여 범위 | 원고 준비 | 커밋·영상 장면·실제 기여자 명단 대조 |
| 최종 폼 | 항목 읽기만 완료 | 실제 정보·링크·직접 선택할 설문·동의 확인 후 제출 |

사람 효과 검증은 이번 제출의 필수 단계에서 제외한다. 그 결과를 구현 정확도·사용성 입증으로 대신 표현하지 않는다. [3분 시연 대본](DEMO_RUNBOOK.md), [제품 보완 결과](SUBMISSION_FIXES_RESULTS.md), [수정 전 비평](FINAL_SUBMISSION_CRITIQUE.md)을 함께 참고한다.
