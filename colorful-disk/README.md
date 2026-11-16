# Colorful Disk

Diário de música no estilo Letterboxd: cadastre álbuns e músicas, avalie de 1 a 5 e comente.
Backend Flask + SQLite, frontend em HTML/CSS/JS puro.

## Como rodar
```bash
python -m pip install -r requirements.txt
python app.py
```
Abra http://localhost:5000. Ou dê dois cliques em `rodar.bat` (Windows).

## Funcionalidades
- Cadastro, login e logout (senha com hash, sessão por cookie)
- Adicionar, editar e excluir músicas/álbuns (só quem cadastrou)
- Avaliação de 1 a 5 estrelas (uma por usuário, pode ser alterada)
- Comentários (cada pessoa exclui só os próprios)
- Busca por título, artista ou gênero e filtro por tipo

## Antes de publicar
Defina `SECRET_KEY` por variável de ambiente e rode com gunicorn, sem `debug=True`.
