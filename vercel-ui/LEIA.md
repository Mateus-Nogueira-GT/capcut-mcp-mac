# UI hospedada

Cópia de build de `web/static/index.html`. **Não edite aqui** — edite o original
e rode `make ui` (ou copie de novo), senão as duas versões divergem.

A página é estática. Todo o trabalho acontece no motor local de quem abre:
`window.location.hostname` não é 127.0.0.1, então ela pede pareamento e depois
fala com `http://127.0.0.1:5151` do próprio visitante.
