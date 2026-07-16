# paper/refs — 선행연구 PDF + 분석

RADP 논문(related work / introduction) 작성용 선행연구 모음 (**28편**).

## 파일
- [PAPERS.md](PAPERS.md) — **논문 카탈로그**. (1) RADP-경쟁/관련 28편: 년도·venue(dblp 게재본 확인)·분야·핵심 아이디어·실험 환경·RADP 관련성. (2) 하단 **TII 산업 프레이밍 20편**(역할 A/B/C/D, 전부 IEEE TII DOI 검증). **새 논문 추가 시 여기에 항목 추가** (유지 규칙은 파일 상단).
- [comparison.md](comparison.md) — 서론이 "왜 데이터센터 GPU 대신 엣지 분산추론인가"를 유도하는 방식 비교 (**논문 명시 사실만**). §1–§4: MDI-LLM/EdgeShard/EnergyHarvest. §5: 추가 엣지 5편.
- [recovery-comparison.md](recovery-comparison.md) — **장애 복구 메커니즘을 가진 엣지 계열 5편**(Petals/JARVIS/QEIL/Parallax/FTPipeHD)의 복구 방식 축별 비교(복구 단위·redundancy·reactive/proactive). related work §B(fault tolerance) 근거.
- [TII-industrial-refs.md](TII-industrial-refs.md) — **TII 제출용 산업 인용 후보**(2026-07-08). 역할별(A=LLM-in-industry, B=분산추론, C=offloading, D=fault-tolerance) + 원문 인용 문구 + intro 배치 제안. RADP는 TMC→**TII** 제출로 변경.
- `*.pdf` — 논문 원문. 파일명 컨벤션: `{SystemName}_{Full-Title-With-Dashes}.pdf` (시스템명 없으면 제목만). TII 20편 중 arXiv 있는 2편만 PDF, 나머지는 유료라 메타데이터만.

## 주의
- 분석 문서(PAPERS.md §상세, comparison.md §1–§3·§5)는 각 논문에 **실제 명시된 사실만** 기록. RADP 관련성/시사점 항목만 해석이며 인용 시 구분할 것.
- venue는 dblp로 게재본 확인 (EdgeShard→IoT-J, Jupiter→INFOCOM, MDI-LLM→LANMAN, HexGen→ICML, HexGen-2→ICLR, LLM-PQ→PPoPP, EnergyHarvest→GLOBECOM). 나머지 arXiv 표기는 dblp에 CoRR만 있는 실제 preprint.
- 중복 정리 이력: MDI-LLM/Petals/EdgeShard/LBRCQT 사본 각 1 제거 (md5 확인).
