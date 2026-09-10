"""Archive Context Engine / Story Engine / Context Store.

Motor determinístico (sin llamadas de IA adicionales, ver
``docs/EDITORIAL_CONTEXT.md``) que recupera antecedentes del archivo propio de
La Voz Riojana y de fuentes oficiales para enriquecer la redacción editorial
existente (``pipeline/node_webapp/editorial.py``) sin reemplazarla.

El índice de este paquete (``data/derived/editorial_context.sqlite3``) es
DERIVADO, RECONSTRUIBLE Y NO AUTORITATIVO: las colas JSON de
``utils/file_manager.py`` siguen siendo el estado autoritativo del pipeline.
"""
