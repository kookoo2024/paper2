# 评分标准回归用例

每个用例一个文件夹：

```text
eval_cases/
  18-全对/
    answer.png
    expected.json
```

`answer.png` 放学生答卷截图。图片已被 `.gitignore` 排除，默认不入库。

`expected.json` 示例：

```json
{
  "question_num": "18",
  "max_score": 17,
  "expected_total": 17,
  "items": [
    {"point": "取PD中点N，MN∥CD且MN=½CD", "full": 1, "got": 1},
    {"point": "证AB∥MN且AB=MN，得平行四边形，BM∥AN", "full": 2, "got": 2}
  ]
}
```

`items` 省略时只比较总分；`answer`、`rubric` 省略时读取
`zhixue_simple_config.json` 里的当前标准。

运行：

```powershell
.\venv\Scripts\python.exe eval.py --dry-run
.\venv\Scripts\python.exe eval.py
```

报告会写到 `eval_reports/`，包括总分误差、逐点一致率、误给分和漏给分。
