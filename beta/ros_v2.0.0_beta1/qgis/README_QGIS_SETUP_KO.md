# QGIS 영상(57:53–1:09:58) 재현

1. QGIS 3.x 설치 후 Ctrl+Alt+P로 Python Console 열기.
2. 실험 폴더 경로 확인: C:/Users/USER/Downloads/experiment_.../qgis/.
3. Console에서 `import runpy; runpy.run_path(r"C:/Users/USER/Downloads/experiment_.../qgis/setup_qgis_layers.py")` 실행.
4. Actual=초록, LEFT=파랑, CENTER=회색, RIGHT=빨강, 실제 TimeStep/목표 Index 레이블 자동 적용.
5. `experiment_layers.qgz`가 같은 폴더에 생성되어 저장 후 재사용 가능.
6. Plugin > Manage and Install Plugins에서 TMS for Korea / TMS4 Korea를 검색, 사용 가능한 경우 VWorld Satellite 추가. 현재 서비스 정책/API 키를 준수.
7. CSV 위경도는 EPSG:4326이며 X=Longitude/Y=Latitude. QGIS TimeStep과 MATLAB Time[s]가 일치하는 샘플을 비교.
8. GPS FIX false인 좌표는 실제 이동 궤적 CSV에 포함되지 않음.

QGIS GUI 실행과 VWorld 타일 실물 조회는 Windows QGIS 환경에서 확인해야 합니다.
