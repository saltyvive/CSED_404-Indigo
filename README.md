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
