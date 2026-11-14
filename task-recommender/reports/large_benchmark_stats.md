# Large Benchmark — Data Quality & Statistics

| item | value |
| --- | --- |
| workers | 1000 |
| tasks | 10000 |
| customers | 500 |
| assignments | 100000 |
| train tasks | 8000 |
| test tasks | 2000 |
| accepted | 61631 |
| rejected | 38369 |
| scheme | E |
| seed | 42 |

## Duplicate checks (computed from the emitted corpus)

| item | value |
| --- | --- |
| task exact duplicates | 0 |
| task title duplicates | 0 |
| task unique titles | 10000 / 10000 |
| task near-dup collisions | 0 |
| task near-dup rate | 0.0000% |
| task near-dup resamples | 651 |
| resume exact duplicates | 0 |
| resume near-dup collisions | 0 |
| resume near-dup rate | 0.0000% |
| resume near-dup resamples | 1641 |

Exact duplicates use normalized SHA-256; title duplicates use the normalized title set; near-duplicates use 64-bit simhash with Hamming distance <= 3. Exact/title/near counters are recomputed from the emitted texts, while the resample counters record generator retries.

## Category distribution

| item | value |
| --- | --- |
| brand_design | 834 |
| consulting_research | 833 |
| content_writing | 834 |
| data_annotation | 833 |
| ecommerce_ops | 833 |
| marketing_campaign | 833 |
| recruitment | 833 |
| software_dev | 834 |
| training_course | 833 |
| translation_localization | 833 |
| ui_ux_design | 834 |
| video_production | 833 |

## Industry distribution

| item | value |
| --- | --- |
| 人力资源 | 500 |
| 企业服务 | 500 |
| 农业 | 500 |
| 制造业 | 500 |
| 医疗健康 | 500 |
| 半导体 | 500 |
| 宠物 | 500 |
| 家居 | 500 |
| 教育 | 500 |
| 文旅 | 500 |
| 新能源 | 500 |
| 新能源汽车 | 500 |
| 游戏 | 500 |
| 物流 | 500 |
| 美妆 | 500 |
| 跨境电商 | 500 |
| 连锁餐饮 | 500 |
| 酒旅 | 500 |
| 金融科技 | 500 |
| 零售 | 500 |

## Budget (midpoint, CNY)

| item | value |
| --- | --- |
| min | 3,850 |
| mean | 13,075 |
| max | 28,800 |

## Duration (days)

| item | value |
| --- | --- |
| min | 3 |
| mean | 20.1 |
| max | 60 |

## Text lengths (characters)

| item | value |
| --- | --- |
| task_text min/mean/max | 167 / 210.8 / 280 |
| resume_text min/mean/max | 356 / 393.0 / 449 |

## Resume completeness (fraction of resumes containing each section)

| item | value |
| --- | --- |
| name | 100.0% |
| city | 100.0% |
| skills | 100.0% |
| projects | 100.0% |
| certifications | 100.0% |
| experience | 100.0% |

## Assignment outcomes

| item | value |
| --- | --- |
| rating distribution | {"1": 2421, "2": 14218, "3": 14554, "4": 18356, "5": 12082} |
| on-time rate | 59.50% |

## Split outcomes

| split | assignments | accepted | rejected | mean rating | on-time |
| --- | --- | --- | --- | --- | --- |
| train | 80000 | 49323 | 30677 | 3.381 | 59.41% |
| test | 20000 | 12308 | 7692 | 3.378 | 59.90% |

## Gold definition

| item | value |
| --- | --- |
| definition | latent-best worker (argmax DGP true-match) in the task's exposure pool |
| exposure pool size | 10 |
| distinct gold workers | 964 |
| gold accepted the task | 7681 / 10000 (76.81%) |
| max gold share | 0.58% |
