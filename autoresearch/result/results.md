# Autoresearch results

![ROUGE-L results](results.png)

| run_id | model_id | kind | epochs | lrm | batch size | rouge_l | delta_vs_base | eval_count | description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base-20261003T055813854041Z-f20494 | gpt-4.1-nano | base | — | — | — | 0.1354 | 0.0000 | 100 | Base GPT-4.1-nano |
| sft-20261003T062945390909Z-503fc5 | gpt-4.1-nano-2025-04-14.ft-6dae574b63474a92851f39ca51f0638a-auto-c135ebb7 | sft | 1 | 0.1000 | auto | 0.2065 | 0.0711 | 100 | Baseline SFT improved mean ROUGE-L by 0.0711 versus base; 93 scored and 7 content-filtered rows |
| **sft-20261003T092447033004Z-282779** | **gpt-4.1-nano-2025-04-14.ft-4cd6ff3d7d364efe87a7b61e841c166c-auto-e7728b22** | **sft** | **2** | **0.1000** | **auto** | **0.2237** | **0.0884** | **100** | **Two epochs improved mean ROUGE-L by 0.0172 versus the one-epoch SFT; 94 scored and 6 content-filtered rows** |
| sft-20261003T112326756160Z-8929f0 | gpt-4.1-nano-2025-04-14.ft-444ca08ff141449fbbc8671ecc14ca0b-auto-c11e695e | sft | 3 | 0.1000 | auto | 0.2216 | 0.0862 | 100 | Three epochs scored 0.0022 below the retained two-epoch SFT; 97 scored and 3 content-filtered rows |
