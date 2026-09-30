"""The pages' files: the calendar and "Goals & plan" read their data from encrypted files in
a bucket at Google Cloud Storage (DESIGN_miniapp_storage.md).

`recipe` holds the key, the names and the encryption (§5), `bucket` the four requests to
Google (§12), and `sync` the step after every command (§6) together with the fill and the
removal that `sm data publish` and `sm data unpublish` run (§9).
"""
