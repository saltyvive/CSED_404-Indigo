# MagAir · 장치 기반 수집과 모델링

사용자가 제작한 자세·높이 조절 장치와 **50 × 30 mm 스윗 스팟의 21열 × 13행(273점)**을 사용하는 현재 작업 공간입니다. 2026-11-23 사용자 요청으로 초기 데모에서 분리했습니다. 이전 가능성 실험은 [demo/](../demo/)에 보존합니다.

## 현재 범위

- **2026-11-25: 앱 1.21.0(26) 접촉·공중 통합 A/B 시험.** 0 mm는 **1+3회차**, 3 mm는 **1회차**만 함께 비교합니다. 접촉 추정은 청록색, 공중 추정은 보라색, 불확실하면 주황색입니다. [사용법·방식·학습 자료 재생 결과](docs/JOINT_HEIGHT_LIVE_TEST.md). 별도 공중 반복 검증은 아직 없습니다.
- **2026-11-25: 높이 3 mm·비접촉 첫 273점 분석 및 앱 1.20.0(25) 실시간 A/B 반영.** φ=0°·θ=90°·α=0°를 유지합니다. [높이별 실시간 사용법](docs/HOVER3_LIVE_TEST.md). [0/3 mm 비교 결과](evaluation/HOVER3_PASS1_RESULTS.md): 높이 분류는 아직 안정적이지 않으며, 이때는 선택한 높이 조건의 위치 추정 시험으로 도입했습니다. 단일 높이 모드는 통합 시험 추가 후에도 유지합니다.
- iPad 수집 앱, φ·θ·α·펜촉 높이·접촉 라벨, 중력 기준 iPad 경사 기록.
- 행별 시작/종료 배경과 정지점 수집, 원본 파일 보관, 완료 이력 복원.
- 3회차까지 819번의 배치를 수집했습니다. 앱 1.18은 보간 A·반복 패턴 k-NN B 각각 1/2/3/12/23/13/123 조합을 실시간 비교하며 기본값은 A123입니다. 여러 자세를 자유롭게 사용하는 성능은 아직 검증하지 않았습니다.
- 같은 φ=0°·θ=90°·α=0°·높이 0 mm에서 A12/B12로 3회차를 먼저 평가한 뒤 A123/B123을 만들었습니다. 학습에 쓰지 않은 회차 평가와 학습 자료 재생을 구분하며, 123은 독립 평가가 없습니다.
- 1.17.1부터 사용자 요청으로 3회차는 1→13행, 1회차와 같은 지그재그 순서입니다. 준비 3초·측정 2초와 고정한 A/B 모델을 유지합니다.

장치 설정은 사람이 입력하는 정답 라벨입니다. 실제 펜의 자세/높이를 자동 측정한 값이 아니며 현재 추론 입력도 아닙니다. 실시간 추정은 iPad 자력계의 3축 자기장을 사용합니다.

## 구성과 실행

`MagAir/`와 `MagAir.xcodeproj/`는 함께 이동 가능한 앱 프로젝트입니다. `scripts/`는 분석 도구, `tests/`는 구현 검사, `docs/`는 현재 수집 절차입니다. 이전 파일을 읽는 데 필요한 일부 코드와 검사 도구는 데모에서 이어받았습니다. 앱의 화면은 **273점 수집 / A/B 실시간 테스트**로 구분합니다.

연구 앱은 기존 `com.chohyeonjun.magair.collector` 식별자를 유지해 설치된 앱의 데이터와 완료 이력을 이어받습니다. 표시 이름은 **MagAir Research**입니다. 데모 프로젝트는 별도의 식별자를 사용합니다.

- [준비 3초·수집 2초·자동 진행 사용법](docs/FAST_COLLECTION.md)
- [3 mm 비접촉 수집 안내](docs/HOVER_3MM_COLLECTION.md)
- [3 mm 1회차 분석·0/3 mm 분리 가능성](evaluation/HOVER3_PASS1_RESULTS.md)
- [0/3 mm 조건별 A/B 실시간 시험](docs/HOVER3_LIVE_TEST.md)
- [3회차·7개 조합 A/B 평가와 학습량 분석](evaluation/COMBINATIONS_RESULTS.md)
- [2회차 평가 결과](evaluation/PASS2_RESULTS.md)
- [회차 간 사전 평가 기록표](evaluation/README.md)
- [원본 ZIP과 복원 안내](../datasets/README.md)
- [φ·θ·α 정의와 사후 확인 라벨](docs/FIXTURE_POSE_LABELS.md)
- [273점 수집 절차](docs/PRINTED_GRID_PROTOCOL.md)
- [첫 회차 실시간 모델과 제한](docs/PRINTED_GRID_PASS1_LIVE.md)
- [인쇄 도면](../output/pdf/sweet_spot_50x30mm_pitch2p5mm_a4_landscape.pdf)

이 폴더에서 실행합니다.

```sh
open MagAir.xcodeproj
mkdir -p build/tests
swiftc -module-cache-path build/SwiftModuleCache \
  MagAir/Core/Experiment.swift MagAir/Core/EdgeExperiment.swift MagAir/Core/DenseGridProtocol.swift \
  MagAir/Core/PrintedGridProtocol.swift MagAir/Core/FixturePoseAnnotation.swift MagAir/Core/PrintedTimingAnnotation.swift \
  MagAir/Core/GridLiveModel.swift MagAir/Core/SessionStore.swift \
  tests/CoreTests.swift tests/PrintedGridProtocolTests.swift -o build/tests/CoreTests
build/tests/CoreTests "$PWD/build/tests"
python3 -m unittest discover -s tests -p 'test_*.py'
```

## 데이터 보존

`data/`(원본 작업 사본), `reports/`(생성 결과), `build/`(빌드)는 Git에서 제외합니다. 원본은 사용자 요청에 따라 저장소 루트 `datasets/`에 세션별 ZIP과 해시 목록으로 커밋합니다. 첫 회차 `printed-grid-20261123-pass1` 자료와 보고서를 이 폴더에 복사하고 SHA-256으로 원본과 일치함을 확인했습니다. `demo/` 아래의 기존 로컬 사본은 삭제하지 않았으며 앞으로 명령은 이 폴더의 자료를 기준으로 실행합니다. 과거 원본의 식별자와 내용은 변경하지 않습니다.
