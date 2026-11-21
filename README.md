# CSED 404 · Team Indigo

iPad 자력계와 Apple Pencil을 이용해 화면 밖 책상 영역에서 입력을 추정하는 모바일 및 유비쿼터스 프로젝트입니다. 자력계가 펜 움직임에 유의미하게 반응하는 영역은 **스윗 스팟(sweet spot)**으로 부릅니다.

## 현재 구성

기존 작업은 [`demo/`](demo/)에 모았습니다. 손으로 맞춘 펜 자세와 위치 표식으로 가능성을 확인한 초기 프로토타입입니다. 정지점의 자력 지도를 만들고 보간해 좌표를 추정하는 방식이며, 통제된 자세·높이·접촉 정답을 갖춘 정식 학습·평가 환경은 아직 구축하지 않았습니다.

```text
demo/
  MagAir/             iPad 수집 앱과 기존 데모 모델
  MagAir.xcodeproj/   Xcode 프로젝트
  scripts/           분석·지도 생성·검증 도구
  tests/             구현 검증
  docs/              기존 실험 프로토콜
  README.md          데모 실행 방법과 실험 기록
  data/              원본 측정 자료 · 로컬 전용
  reports/           생성 결과 · 로컬 전용
  build/             빌드 산출물 · 로컬 전용
```

데모의 상세 안내는 [demo/README.md](demo/README.md)를 참고하세요. 새 학습 환경은 데이터 수집 장치와 실험 설계가 정해진 뒤 별도 작업 폴더로 만들 예정이며, 현재는 생성하지 않았습니다. `mobile_programming_assignment/`는 별도 Android 과제로, 이 저장소에서 추적하지 않습니다.

## 인쇄용 스윗 스팟 도면

[A4 가로 도면 PDF](output/pdf/sweet_spot_50x30mm_pitch2p5mm_a4_landscape.pdf)는 297 × 210 mm 용지에 50 × 30 mm 스윗 스팟을 배치합니다. 영역의 왼쪽 아래 꼭짓점은 **용지 자체의 왼쪽 아래**에서 오른쪽으로 115 mm, 위로 55 mm입니다. 빨간 실선 테두리와 검은 점을 사용하며, 가로·세로 모두 2.5 mm 간격으로 **21열 × 13행 = 273점**을 표시합니다. 경계와 네 모서리도 포함하며, 점 지름은 0.45 mm입니다.

**A4 가로 / 실제 크기 100% / 페이지 맞춤·자동 축소 끄기**로 인쇄하세요. 도면에는 스윗 스팟 테두리와 점만 표시합니다. 인쇄 후 직사각형의 가로 50 mm·세로 30 mm와 용지 모서리 기준 오프셋을 실측해 인쇄 배율·위치 오차를 확인합니다. 테두리 치수와 오프셋은 빨간 선의 중심선 및 점 중심을 기준으로 합니다. 이 도면은 인쇄 자료이며, 기존 데모 앱의 9×9 수집 절차나 모델을 변경하지 않습니다.

재생성 소스는 [generate_sweet_spot_template.py](output/pdf/generate_sweet_spot_template.py)입니다. `reportlab`이 설치된 Python으로 실행합니다.

```sh
python3 output/pdf/generate_sweet_spot_template.py
```

## 데모 개발

저장소 루트에서 Xcode 프로젝트를 열려면 다음 명령을 사용합니다.

```sh
open demo/MagAir.xcodeproj
```

분석·테스트 명령은 `demo/` 안에서 실행합니다.

```sh
cd demo
python3 -m unittest discover -s tests -p 'test_*.py'
```

새 커밋은 `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` 형식을 사용합니다. 작업 규칙은 [AGENTS.md](AGENTS.md)에 기록했습니다.
