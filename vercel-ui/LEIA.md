# O que está hospedado aqui

| Rota | Tela | Precisa de |
|---|---|---|
| `/` | fala **direto** com o motor em `127.0.0.1` | uma permissão do Chrome, por máquina |
| `/relay` | enfileira trabalho, o motor **puxa** de fora | store Neon conectado ao projeto |

**Comece pela `/`.** Ela não precisa de banco nem de relay. A única coisa que ela
exige é liberar o acesso à rede local uma vez por navegador — o Chrome 142+ passou
a pedir isso, e sem a permissão a chamada falha em silêncio.

Em `chrome://settings/content/localNetworkAccess`, adicione
`https://capcut-front.vercel.app` em "Pode acessar dispositivos da rede local".

A `/relay` existe para quando essa permissão não é aceitável (parque não
gerenciado, navegador que não oferece a opção). Ela custa um banco e uma fila;
a `/` custa um clique. Não use a `/relay` sem precisar.

`static/index.html` é cópia de build de `web/static/index.html`, e
`static/relay.html` é a tela do relay. Edite os originais, não estas cópias.
