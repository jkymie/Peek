# Compartilha Tela

Aplicação web para transmitir a tela do computador para um grupo pequeno de amigos (até 10 pessoas). O áudio da conversa continua no Discord; este projeto cuida **apenas da transmissão de tela**.

> **Status:** em construção. Este README descreve a arquitetura e o fluxo planejados. Algumas seções serão ajustadas à medida que o código for escrito.

---

## Sumário

- [Visão geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Stack](#stack)
- [Pré-requisitos](#pré-requisitos)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Configuração](#configuração)
- [Como rodar](#como-rodar)
- [Como os amigos se conectam](#como-os-amigos-se-conectam)
- [Desenvolvimento](#desenvolvimento)
- [Segurança](#segurança)
- [Limitações conhecidas](#limitações-conhecidas)
- [Solução de problemas](#solução-de-problemas)
- [Roadmap](#roadmap)

---

## Visão geral

- Uma pessoa por vez (ou mais) clica em **Transmitir minha tela** no navegador.
- Os demais participantes da sala assistem em tempo real.
- O servidor roda no PC do anfitrião, apenas quando o grupo for usar.
- O acesso é restrito ao grupo por meio de uma rede privada (Tailscale) e de uma senha da sala.

## Arquitetura

```
 Quem transmite (navegador)
          │  vídeo da tela (WebRTC, enviado uma única vez)
          ▼
 ┌─────────────────────────── PC do anfitrião ───────────────────────────┐
 │                                                                        │
 │   LiveKit Server (SFU)  ◄── tokens ──  Back-end Python (FastAPI)       │
 │   repassa o vídeo                      gera tokens e serve a página    │
 │                                                                        │
 └────────────────────────────────────────────────────────────────────────┘
          │  uma cópia do vídeo para cada espectador
          ▼
 Espectadores (navegador)

 Toda a comunicação passa pela rede privada do Tailscale.
```

O fluxo de entrada na sala é:

1. O participante abre a página servida pelo FastAPI e informa nome e senha da sala.
2. O back-end valida a senha e gera um **token de acesso** do LiveKit com as permissões do participante.
3. O navegador usa o token para se conectar ao LiveKit Server.
4. Quem clicar em **Transmitir minha tela** publica a tela; os demais recebem o vídeo.

## Stack

| Camada | Tecnologia | Função |
|---|---|---|
| Servidor de mídia | [LiveKit Server](https://github.com/livekit/livekit) | SFU: recebe e repassa o vídeo via WebRTC |
| Back-end | Python 3.12+, FastAPI, Uvicorn | Geração de tokens e entrega do front-end |
| SDK do back-end | `livekit-api` | Criação de tokens de acesso |
| Configuração | `pydantic-settings` + arquivo `.env` | Leitura de variáveis de ambiente |
| Front-end | HTML, CSS e JavaScript puro + `livekit-client` | Interface, captura de tela (`getDisplayMedia`) e reprodução |
| Rede e HTTPS | [Tailscale](https://tailscale.com) | Acesso privado dos amigos e certificado HTTPS |
| Dependências Python | [uv](https://docs.astral.sh/uv/) | Ambiente virtual, dependências e lockfile |
| Qualidade | Ruff, pytest, pre-commit, gitleaks | Lint, formatação, testes e bloqueio de segredos |
| CI | GitHub Actions | Lint e testes a cada push |

## Pré-requisitos

No PC do anfitrião:

- [Git](https://git-scm.com/)
- [Python 3.12 ou superior](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- LiveKit Server, de uma destas formas:
  - **binário** `livekit-server` ([instruções de instalação](https://docs.livekit.io/home/self-hosting/local/)), ou
  - **Docker** com Docker Compose
- [Tailscale](https://tailscale.com/download) instalado e autenticado
- Upload de internet suficiente (ver [Limitações conhecidas](#limitações-conhecidas))

Em cada participante:

- Navegador baseado em Chromium (Chrome ou Edge) atualizado
- Tailscale instalado, com acesso à máquina do anfitrião

## Estrutura do repositório

```
compartilha-tela/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI: rotas e arquivos estáticos
│   │   ├── config.py        # leitura do .env (pydantic-settings)
│   │   └── tokens.py        # geração de tokens do LiveKit
│   └── tests/
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── vendor/              # livekit-client em versão fixa
├── infra/
│   ├── docker-compose.yml   # LiveKit Server via Docker
│   └── livekit.yaml         # configuração do LiveKit
├── .github/workflows/ci.yml
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── pyproject.toml
├── uv.lock
└── README.md
```

## Configuração

Copie o arquivo de exemplo e preencha os valores:

```bash
cp .env.example .env
```

| Variável | Descrição | Exemplo |
|---|---|---|
| `LIVEKIT_URL` | Endereço WebSocket do LiveKit visto pelos navegadores | `wss://meu-pc.exemplo.ts.net:8443` |
| `LIVEKIT_API_KEY` | Chave de API do LiveKit | `devkey` |
| `LIVEKIT_API_SECRET` | Segredo da API do LiveKit (**nunca** vai para o front-end) | `troque-por-um-valor-longo` |
| `ROOM_NAME` | Nome da sala padrão | `amigos` |
| `ROOM_PASSWORD` | Senha que os participantes digitam para entrar | `troque-esta-senha` |
| `APP_HOST` | Endereço em que o FastAPI escuta | `127.0.0.1` |
| `APP_PORT` | Porta do FastAPI | `8000` |

Em `infra/livekit.yaml`, defina as mesmas chaves (`keys`) e informe o IP do seu PC na rede do Tailscale em `rtc.node_ip`, para que o vídeo trafegue pela rede privada:

```yaml
port: 7880
rtc:
  tcp_port: 7881
  udp_port: 7882
  node_ip: 100.x.y.z   # IP do PC no Tailscale (veja com: tailscale ip -4)
keys:
  devkey: troque-por-um-valor-longo
```

## Como rodar

### 1. Clonar e instalar as dependências

```bash
git clone git@github.com:SEU-USUARIO/compartilha-tela.git
cd compartilha-tela
uv sync
uv run pre-commit install
```

### 2. Subir o LiveKit Server

Com o binário:

```bash
livekit-server --config infra/livekit.yaml
```

Ou com Docker:

```bash
docker compose -f infra/docker-compose.yml up -d
```

### 3. Subir o back-end

```bash
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Durante o desenvolvimento, adicione `--reload` para recarregar ao salvar arquivos.

### 4. Publicar com HTTPS na rede do Tailscale

O navegador só libera a captura de tela em páginas HTTPS, e uma página HTTPS só pode se conectar ao LiveKit via `wss://`. Por isso, tanto a aplicação quanto o LiveKit são expostos com o `tailscale serve`:

```bash
# Aplicação web em https://<maquina>.<tailnet>.ts.net
tailscale serve --bg 8000

# LiveKit em wss://<maquina>.<tailnet>.ts.net:8443
tailscale serve --bg --https=8443 http://localhost:7880
```

> A sintaxe do `tailscale serve` mudou entre versões. Confirme com `tailscale serve --help` na versão instalada.

### 5. Testar

Abra `https://<maquina>.<tailnet>.ts.net`, entre na sala e clique em **Transmitir minha tela**. Abra a mesma página em outra aba ou outro dispositivo para ver a transmissão.

## Como os amigos se conectam

1. O anfitrião compartilha a máquina com cada amigo pelo painel do Tailscale (*Share* na máquina) ou os convida para a rede.
2. Cada amigo instala o Tailscale e aceita o convite.
3. O amigo abre o endereço `https://<maquina>.<tailnet>.ts.net` e entra com a senha da sala.
4. A call continua normalmente no Discord.

> Confira os limites atuais do plano gratuito do Tailscale; eles já mudaram ao longo do tempo.

## Desenvolvimento

```bash
uv run ruff check .        # lint
uv run ruff format .       # formatação
uv run pytest              # testes
uv run pre-commit run --all-files
```

O GitHub Actions executa lint e testes a cada push e pull request (`.github/workflows/ci.yml`).

Para adicionar uma dependência:

```bash
uv add nome-do-pacote          # dependência da aplicação
uv add --dev nome-do-pacote    # dependência de desenvolvimento
```

## Segurança

- O arquivo `.env` está no `.gitignore` e **nunca** deve ser commitado. Use o `.env.example` como referência.
- O `LIVEKIT_API_SECRET` fica apenas no back-end. O front-end recebe somente tokens temporários.
- O pre-commit roda o `gitleaks` para bloquear commits que contenham segredos.
- Os serviços escutam apenas em `127.0.0.1` e são expostos exclusivamente pela rede do Tailscale, sem portas abertas no roteador.
- Troque a senha da sala e as chaves do LiveKit se alguém sair do grupo.
- Mantenha LiveKit, Tailscale e as dependências Python atualizados.

## Limitações conhecidas

- **Upload do anfitrião:** como o servidor roda em casa, todo o vídeo sai pela internet do anfitrião, uma cópia por espectador. Para 9 espectadores em 720p, estime de 13 a 20 Mbps de upload; em 1080p, bem mais. Meça sua conexão antes de usar com o grupo todo.
- **Disponibilidade:** o serviço só funciona enquanto o PC do anfitrião estiver ligado e com os processos em execução.
- **Áudio da tela:** a captura do som do sistema funciona bem no Chrome/Edge no Windows, mas é limitada no macOS e no Linux.
- **Tailscale obrigatório:** todos os participantes precisam instalá-lo.

## Solução de problemas

| Sintoma | Causa provável | O que verificar |
|---|---|---|
| Botão de transmitir não funciona | Página aberta sem HTTPS | Acesse pelo endereço `https://...ts.net` |
| Conecta, mas não aparece vídeo | `rtc.node_ip` incorreto | Compare com `tailscale ip -4` |
| Erro de conexão ao LiveKit | `LIVEKIT_URL` errado ou sem `wss://` | Revise o `.env` e o `tailscale serve` |
| Token inválido | Chaves diferentes entre `.env` e `livekit.yaml` | Use o mesmo par de chave e segredo |
| Vídeo travando | Upload insuficiente | Reduza a resolução ou o número de espectadores |

## Roadmap

- [ ] Esqueleto do repositório (`pyproject.toml`, CI, pre-commit)
- [ ] Back-end: validação de senha e geração de tokens
- [ ] Front-end: entrar na sala, transmitir e assistir
- [ ] Testes do back-end
- [ ] Indicador de quem está transmitindo
- [ ] Ajuste de qualidade (resolução e taxa de quadros)
- [ ] Plano B: LiveKit na nuvem caso o upload doméstico não seja suficiente
