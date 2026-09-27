# mokuro-watcher

Roda o [mokuro](https://github.com/kha-white/mokuro) nos capítulos raw que o Kaizoku baixa e publica o par `.cbz` + `.mokuro` numa pasta que o [mokuro-reader](https://github.com/diogovalentte/mokuro-reader) lê por WebDAV.

```
/Medias/Mangas/<Série>/<Cap>.cbz            ← Kaizoku grava
/Medias/Mangas/.mokuro-staging/...          ← mokuro roda aqui
/Medias/Mangas/.mokuro-reader/<Série>/<Cap>.{cbz,mokuro}  ← servido pelo WebDAV
```

## Como funciona

- A cada `SCAN_INTERVAL_SECONDS` varre a biblioteca. Um `.cbz` entra na fila se estiver parado há `MIN_AGE_SECONDS` e se o `<Web>` do `ComicInfo.xml` for de um dos `SOURCES`.
- Na **primeira execução** tudo o que já existe é registrado e ignorado: só capítulos baixados depois são processados.
- **Série nova** na biblioteca: o download inicial é ignorado do mesmo jeito. Os capítulos que chegam são registrados sem processar até passar `SERIES_BASELINE_SECONDS` sem nenhum capítulo novo nela; daí em diante cada capítulo novo é processado. Pra processar o acervo inicial também, use `force`.
- O mokuro tira o título da série da pasta onde o `.cbz` está, que no staging é a do capítulo. Antes de publicar, o `.mokuro` recebe `title` = nome da pasta da série e `title_uuid` = `uuid5` fixo desse nome, pra todos os capítulos caírem na mesma série no reader.
- Um capítulo por vez. O `.cbz` publicado é um hardlink (não ocupa espaço); o `.mokuro` é movido antes do `.cbz`, então o reader nunca lista um volume sem OCR.
- Falha: tenta de novo nas próximas varreduras; depois de `MAX_ATTEMPTS` desiste e avisa no ntfy.
- `.cbz` apagado da biblioteca → o par publicado é apagado também.
- Redownload (mtime/size mudou) → reprocessa.

Pastas começando com `.` na biblioteca são ignoradas.

## Configuração

| Variável | Padrão |
|---|---|
| `LIBRARY_DIR` | `/Medias/Mangas` |
| `OUTPUT_DIR` | `$LIBRARY_DIR/.mokuro-reader` |
| `STAGING_DIR` | `$LIBRARY_DIR/.mokuro-staging` |
| `STATE_DB` | `/state/mokuro-watcher.db` |
| `SOURCES` | `klmanga,rawkuma,jmanga` |
| `SCAN_INTERVAL_SECONDS` | `300` |
| `MIN_AGE_SECONDS` | `120` |
| `SERIES_BASELINE_SECONDS` | `21600` (6h) |
| `MAX_ATTEMPTS` | `3` |
| `MOKURO_TIMEOUT_SECONDS` | `7200` |
| `NTFY_ADDRESS`, `NTFY_TOPIC`, `NTFY_TOKEN` | vazio (sem aviso) |

`OUTPUT_DIR` e `STAGING_DIR` precisam estar no mesmo filesystem da biblioteca (hardlink).

Volumes: `/cache` guarda os modelos do OCR (~900 MB, baixados na primeira execução), `/state` guarda o registro.

## Comandos

```bash
mokuro-watcher run            # loop (padrão)
mokuro-watcher once           # uma varredura e sai
mokuro-watcher force <Série>  # enfileira o acervo antigo de uma série (e encerra a janela de série nova)
mokuro-watcher fix-titles     # corrige título/title_uuid dos .mokuro já publicados (idempotente)
```

Dentro do container: `docker exec mokuro-watcher mokuro-watcher force Skip_to_Loafer`.

## Testes

```bash
uvx --python 3.11 --with pytest pytest -q
```

## Publicação

Push de tag → testes → imagem `ghcr.io/diogovalentte/mokuro-watcher:{tag,latest}` → webhook de redeploy da stack `mokuro-watcher` no Portainer.
