# section-3: 월별 광고 성과

별도 호출 없음 — section-1의 `get_ad_performance`(month, group_by 없음, 최근 6개월) 응답을 빌더가 재사용한다.

## 빌더가 하는 일

- 최근 6개월(M-5~M0) 막대 = 광고비(`metric_keys.cost`), 선 = CPV(`metric_keys.cpv`, 오른쪽 축).
- 값은 각 월 행의 서버 값 그대로. 월 행이 없으면 그 점은 비운다.
