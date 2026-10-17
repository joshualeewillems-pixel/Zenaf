"""Minting pipeline: journal entry → story → prompt pack → (external render)
→ import/mint → lineage/reach.

Zenaf owns the two ends where it has unique context (story extraction,
prompt packs, import/mint); the user owns the middle (external render
tools). The provenance registry (`local_ai.provenance`) is the ledger;
this module is the pipeline that feeds it.

Spec: ~/workspace/zenaf-minting-pipeline-spec.md
"""
