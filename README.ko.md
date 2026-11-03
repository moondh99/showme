# ShowMe

[English README](README.md) · [한국어 3분 시연 영상](https://moondh99.github.io/showme/ShowMe-3min-demo.mp4)

ShowMe는 담당자가 승인한 작업 사진에서 물체를 가리켜, 그 물체에 적용되는 규칙을 확인하는 도구입니다. 담당자는 사진과 메모로 안내서 초안을 만들고 검토한 뒤, 변경 이력이 분리된 승인 링크를 공유합니다.

## 파란 보관표 데모

두 트레이의 표는 비슷하게 생겼지만 용도가 다릅니다. 파란 표를 가리켜 **“교육을 받았으니까 이 표로 장비를 가져가겠습니다.”**라고 물어보세요. ShowMe는 **보관표로 장비를 대여할 수 없다는 승인 문장**을 판정 제목에 표시하고, 교육 이수 또는 책임자 동행은 노란 대여표의 발급 조건으로 구분합니다. [새 복제본의 실제 판정 화면](docs/assets/storage-tags-verdict.png)

### 로컬에서 실행하기

Python 3.10 이상이 필요합니다. 저장소의 루트에서 실행합니다.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/seed_demo.py
python scripts/serve.py
```

1. [한국어 로컬 데모](http://127.0.0.1:8765/demo?lang=ko)를 엽니다. 연출 사진, 승인 메모, 완료 기준은 로그인과 API 키 없이 볼 수 있습니다.
2. 실제 윤곽 선택과 질문을 사용하려면 `.env.example`을 `.env.local`로 복사하고 `MODEL_API_KEY`에 Meta Model API 키를 설정한 뒤 서버를 다시 시작합니다. 키는 서버에서 읽습니다.
3. ‘사진에서 물체 선택’을 누르고 **왼쪽 파란 트레이의 맨 앞 흰색 표 가운데**를 가리킵니다. 위 질문을 보내면 실제 모델이 답합니다. 판정 아래에서 해당 조건과 전체 승인 원문을 확인할 수 있습니다.

`python scripts/seed_demo.py`는 영어·한국어 보관표 데모를 각각 준비합니다. 다시 실행하면 언어별 기존 데모 승인본을 재사용합니다. 기존 4단계 한국어 접수대 데모는 `--scenario reception`으로 준비할 수 있습니다. [작성자 로그인과 저장 범위](docs/LOCAL_RUN.md)

## Meta 모델과 승인 경계

- **SAM 3.1**은 승인된 사진에서 클릭한 물체의 윤곽을 찾습니다.
- **Muse Spark 1.3**은 작성자의 메모를 바탕으로 초안을 만들고, 학습 질문에서는 선택한 물체와 승인 규칙을 연결합니다. 규칙 질문은 별도 검토를 거칩니다.
- **ShowMe**는 초안과 승인본을 분리하고 승인 원문의 인용을 검증합니다. 설명과 완료 확인의 전체 원문을 보여주며, 현장 완료는 작업자가 직접 표시합니다.

데모는 출처가 기록된 AI 연출 사진을 사용합니다. 검증은 통제된 회귀 검사와 내부 실제 API 실행 범위이며, 현장 사용자의 시간 절감과 오류 감소는 별도 평가가 필요합니다. [사진 출처](public/demo/reception-setup/photo-sources.json)

## 검증과 프로젝트 기록

- [제품 결정과 수정 전후 검증](docs/PRODUCT_DECISIONS.md)
- [3분 시연 대본](docs/DEMO_RUNBOOK.md)
- [실제 모델 평가와 지연 개선](docs/R12_TAIL_RESULTS.md)
- [로컬·호스팅 실행 안내](docs/LOCAL_RUN.md)

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -q
node --test tests/*.mjs
```
