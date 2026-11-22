# MagAir · 장치 기반 수집과 모델링

사용자가 제작한 자세·높이 조절 장치와 **50 × 30 mm 스윗 스팟의 21열 × 13행(273점)**을 사용하는 현재 작업 공간입니다. 2026-11-23 사용자 요청으로 초기 데모에서 분리했습니다. 이전 가능성 실험은 [demo/](../demo/)에 보존합니다.

## 현재 범위

- iPad 수집 앱, φ·θ·α·펜촉 높이·접촉 라벨, 중력 기준 iPad 경사 기록.
- 행별 시작/종료 배경과 정지점 수집, 원본 파일 보관, 완료 이력 복원.
- 첫 회차 273점의 보간 지도와 실시간 테스트. 신경망이나 여러 자세를 함께 추정하는 모델은 아직 도입하지 않았습니다.
- 다음 각도 조합과 반복 횟수는 미정입니다. 기존 2·3회차 슬롯은 남아 있지만 이를 다음 필수 수집으로 정한 것은 아닙니다.

장치 설정은 사람이 입력하는 정답 라벨입니다. 실제 펜의 자세/높이를 자동 측정한 값이 아니며 현재 추론 입력도 아닙니다. 실시간 추정은 iPad 자력계의 3축 자기장을 사용합니다.

## 구성과 실행

`MagAir/`와 `MagAir.xcodeproj/`는 함께 이동 가능한 앱 프로젝트입니다. `scripts/`는 분석 도구, `tests/`는 구현 검사, `docs/`는 현재 수집 절차입니다. 이전 파일을 읽는 데 필요한 일부 코드와 검사 도구는 데모에서 이어받았습니다. 앱의 화면은 **273점 수집 / 273점 실시간 테스트**로 구분합니다.

연구 앱은 기존 `com.chohyeonjun.magair.collector` 식별자를 유지해 설치된 앱의 데이터와 완료 이력을 이어받습니다. 표시 이름은 **MagAir Research**입니다. 데모 프로젝트는 별도의 식별자를 사용합니다.

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
  MagAir/Core/PrintedGridProtocol.swift MagAir/Core/FixturePoseAnnotation.swift \
  MagAir/Core/GridLiveModel.swift MagAir/Core/SessionStore.swift \
  tests/CoreTests.swift tests/PrintedGridProtocolTests.swift -o build/tests/CoreTests
build/tests/CoreTests "$PWD/build/tests"
python3 -m unittest discover -s tests -p 'test_*.py'
```

## 데이터 보존

`data/`(원본), `reports/`(생성 결과), `build/`(빌드)는 로컬 전용이며 Git에서 제외합니다. 첫 회차 `printed-grid-20261123-pass1` 자료와 보고서를 이 폴더에 복사하고 SHA-256으로 원본과 일치함을 확인했습니다. `demo/` 아래의 기존 로컬 사본은 삭제하지 않았으며 앞으로 명령은 이 폴더의 자료를 기준으로 실행합니다. 과거 원본의 식별자와 내용은 변경하지 않습니다.
