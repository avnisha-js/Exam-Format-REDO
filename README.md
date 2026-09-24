CORE Phase 1 reads the fixed teacher exam, discovers one hierarchy for the whole document, then numbers that hierarchy in code.

```
python run_core.py
```

Inputs are the files in `input/`. They are read only. Outputs are `output/hierarchy.json`, `output/hierarchy.txt`, and `output/integrity.txt`.

Discovery uses one OpenAI structured call (`EXAM_REDO_MODEL`, default `gpt-4.1`) when `OPENAI_API_KEY` is set. The model returns types and parents for existing source ids. It does not rewrite question text and it does not assign final labels.
