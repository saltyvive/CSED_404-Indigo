# CSED 404 · Team Indigo

iPad 자력계와 Apple Pencil을 이용해 화면 밖 책상 영역에서 입력을 추정하는 모바일 및 유비쿼터스 프로젝트입니다. 자력계가 펜 움직임에 유의미하게 반응하는 영역은 **스윗 스팟(sweet spot)**으로 부릅니다.

## 현재 구성

- [`demo/`](demo/): 273점 도입 전 초기 가능성 실험을 보존한 프로토타입.
- [`research/`](research/): 장치 기반 273점 수집, φ·θ·α·높이 라벨, 현재 모델과 실시간 테스트.
- [`output/pdf/`](output/pdf/): 실측 크기의 인쇄 도면.

2026-11-23 사용자 요청으로 두 작업을 분리했습니다. 현재 작업은 `research/`에서 진행합니다. 새 폴더를 만들었다고 새로운 학습 알고리즘이나 정확도 검증이 완료된 것은 아닙니다. 현재 모델은 첫 회차 273점의 자기장 보간 지도이며, 다른 자세를 위한 다음 수집 조건과 모델 구조는 아직 결정하지 않았습니다.

각 폴더의 `data/`, `reports/`, `build/`는 로컬 전용입니다. 기존 원본은 보존합니다. `mobile_programming_assignment/`는 별도 Android 과제로 Git에서 제외합니다.

## 인쇄용 스윗 스팟 도면

[A4 가로 도면 PDF](output/pdf/sweet_spot_50x30mm_pitch2p5mm_a4_landscape.pdf)는 297 × 210 mm 용지에 50 × 30 mm 스윗 스팟을 배치합니다. 영역의 왼쪽 아래 꼭짓점은 **용지 자체의 왼쪽 아래**에서 오른쪽으로 115 mm, 위로 55 mm입니다. 빨간 실선 테두리와 검은 점을 사용하며, 가로·세로 모두 2.5 mm 간격으로 **21열 × 13행 = 273점**을 표시합니다. 경계와 네 모서리도 포함하며, 점 지름은 0.45 mm입니다.

**A4 가로 / 실제 크기 100% / 페이지 맞춤·자동 축소 끄기**로 인쇄하세요. 도면에는 스윗 스팟 테두리와 점만 표시합니다. 인쇄 후 직사각형의 가로 50 mm·세로 30 mm와 용지 모서리 기준 오프셋을 실측해 인쇄 배율·위치 오차를 확인합니다. 테두리 치수와 오프셋은 빨간 선의 중심선 및 점 중심을 기준으로 합니다.

앱의 **‘273점 수집’**에서 이 도면에 맞춰 한 행 21점과 앞뒤 배경을 묶어 자동 저장합니다. 첫 회차를 완료했고, 기존 세 회차 슬롯은 보존하지만 다음 자세·반복 계획은 미정입니다. [측정 순서와 사용 안내](research/docs/PRINTED_GRID_PROTOCOL.md)를 참고하세요. **1.14.0에서는 완료한 첫 회차 13묶음으로 임시 실시간 모델을 적용**했습니다. [첫 회차 테스트 안내](research/docs/PRINTED_GRID_PASS1_LIVE.md)에 데이터 점검 결과와 한계를 기록했습니다.

재생성 소스는 [generate_sweet_spot_template.py](output/pdf/generate_sweet_spot_template.py)입니다. `reportlab`이 설치된 Python으로 실행합니다.

```sh
python3 output/pdf/generate_sweet_spot_template.py
```

## 현재 작업 실행

저장소 루트에서 Xcode 프로젝트를 열려면 다음 명령을 사용합니다.

```sh
open research/MagAir.xcodeproj
```

분석·테스트 명령은 `research/` 안에서 실행합니다. Swift 검사로 테스트 입력을 생성하는 순서는 [research/README.md](research/README.md)를 참고하세요.

```sh
cd research
python3 -m unittest discover -s tests -p 'test_*.py'
```

새 커밋은 `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` 형식을 사용합니다. 작업 규칙은 [AGENTS.md](AGENTS.md)에 기록했습니다.
