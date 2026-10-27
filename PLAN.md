# 🗺️ Plano de desenvolvimento do Peek

Este documento divide em fases o trabalho necessário para levar o Peek do estado atual (apenas o `README.md`) até a versão 1.0 descrita no README, com a **interface gráfica como parte central do produto**, e não como um acabamento final.

---

## Resumo executivo

- O projeto tem **duas frentes que precisam convergir**: o *núcleo* (captura, WebRTC, túnel, áudio) e a *interface* (janela PySide6 + página do espectador).
- Para que a interface não vire um "remendo" no fim, o plano define cedo uma **camada de controle** (`StreamSession`) que a janela e o modo `--headless` usam do mesmo jeito. Assim, a interface pode ser desenhada e prototipada em paralelo ao núcleo.
- A ordem das fases reduz primeiro os **maiores riscos técnicos** (captura + `aiortc`, áudio sem o Discord) antes de investir em polimento.
- A versão 1.0 só é considerada pronta após o **teste com alguém que não programa** (Fase 9).

| Fase | Nome | Frente | Depende de |
|---|---|---|---|
| 0 | Fundação do repositório | Infra | — |
| 1 | Vídeo local de ponta a ponta | Núcleo | 0 |
| 2 | Design da interface (UX) | Interface | 0 (paralela à 1) |
| 3 | Link público automático | Núcleo | 1 |
| 4 | Helper de áudio sem o Discord | Núcleo (C++) | 0 (paralela à 1–3) |
| 5 | Áudio integrado ao núcleo | Núcleo | 1, 4 |
| 6 | Qualidade e FPS em tempo real | Núcleo | 1 |
| 7 | Janela do Peek (PySide6) | Interface | 2, 3, 5, 6 |
| 8 | Página do espectador final | Interface | 1, 2 |
| 9 | Empacotamento, testes e lançamento 1.0 | Entrega | 7, 8 |
| 10 | Depois da 1.0 | Evolução | 9 |

---

## 🎯 Marco 1: versão testável até quinta-feira (29/10/2026)

Faltam cerca de 3,5 dias úteis (segunda a quinta). Isso não comporta todas as fases acima, então este marco faz um **corte vertical**: um pedaço fino de cada frente (núcleo, link, janela, espectador), o suficiente para testar o fluxo principal **com a interface**. O restante continua nas fases normais.

### O que "testável" significa neste marco

Alguém da equipe abre o Peek (`python -m host`), escolhe uma tela ou janela **pela janela do Peek**, clica em **Começar a transmitir**, copia o link e manda para 1 ou 2 pessoas em **outra rede**. Elas assistem pelo navegador, e quem transmite vê o contador e consegue **Parar**.

### Escopo

| Entra até quinta | Fica para depois |
|---|---|
| Captura de monitor e de janela (Fase 1) | Miniaturas ao vivo (na quinta, a lista mostra só os nomes) |
| `aiortc` + `aiohttp` + sinalização + `StreamSession` (Fase 1) | Opção **Personalizada** e troca de qualidade durante a transmissão (Fase 6) |
| Link público via `cloudflared` com token na URL (Fase 3, versão mínima) | Reinício automático do `cloudflared` |
| Janela PySide6 mínima: lista de fontes, qualidade (3 presets: Econômica, Equilibrada, Nítida), **Começar**, **Copiar link**, contador, **Parar**, erro genérico em linguagem simples (Fase 7, versão mínima) | Telas de erro específicas, tema escuro, lembrar configurações |
| Página do espectador básica com o aviso "Clique para ativar o som" (Fase 8, versão mínima) | Reconexão automática, indicador de qualidade |
| Modo `--headless` para depurar | `Peek.exe` (Fase 9) |
| **Meta extra:** `peek-audio.exe` com exclusão do Discord (Fases 4 e 5) — feito em 27/10 | Detecção do Discord aberto depois |

> **Áudio:** é o item de maior risco do prazo (C++ e WASAPI). Se não ficar estável até quarta à noite, a versão de quinta sai **só com vídeo**, e o pessoal continua ouvindo pela call do Discord. Não vale usar a captura do sistema inteiro como plano B, porque isso devolve a voz da call para os amigos (o eco que o Peek existe para evitar).

### Cronograma

| Dia | Entrega | Como verificar |
|---|---|---|
| **Seg 26/10** | Fase 0 reduzida (estrutura, `requirements.txt`, `ruff`, logging). `capture/video.py` lista e captura monitores/janelas | Um script salva um frame capturado em PNG |
| **Ter 27/10** | `tracks.py` + `server.py` + `web/` mínimo + `StreamSession` + `--headless` | Outro dispositivo na mesma rede assiste via `--no-tunnel` |
| **Qua 28/10** | `tunnel.py` com token na URL. Janela PySide6 mínima ligada à `StreamSession` (com `qasync`) | Transmissão iniciada **pela janela** é assistida de outra rede (4G) |
| **Qui 29/10 (manhã)** | Correções, roteiro de teste, prazo final para decidir se o áudio entra | Roteiro abaixo executado de ponta a ponta |
| **Qui 29/10 (tarde)** | **Sessão de teste** | Problemas encontrados registrados como issues |

Se houver uma segunda pessoa, ela pode desenvolver o `audio-helper` (Fase 4) em paralelo desde segunda, sem bloquear o resto.

### Roteiro de teste de quinta

Ensaio automatizado em 27/10 (sessão real, link público e dois espectadores `aiortc` conectando pelo link): 12 de 12 verificações passaram. Os testes com pessoas foram feitos no mesmo dia; continuam abertos a impressão de qualidade/CPU e a confirmação visual da troca de fonte.

- [x] Abrir com `python -m host`: nenhuma janela de terminal extra aparece além da usada para iniciar — conferido em 27/10
- [ ] Transmitir a **tela inteira** e depois **uma janela específica** — ensaio: monitor e troca para uma janela funcionaram; falta conferir a imagem no navegador
- [x] Copiar o link e abrir em Chrome, Edge e Firefox, sendo pelo menos um espectador em outra rede — validado em 27/10 (link pronto em ~9 s)
- [x] Contador mostra 1, 2 e volta a 1 quando alguém fecha a aba — ensaio em 27/10
- [ ] Testar Econômica e Nítida, anotando a impressão de nitidez, travamentos e uso de CPU — ensaio: 480p → 1080p sem reconectar; falta a impressão visual e a CPU
- [x] **Parar** derruba os espectadores, e o link antigo deixa de funcionar — ensaio em 27/10: espectador recebe "terminou", link responde 502, nenhum processo fica para trás
- [x] Desligar a internet antes de começar e conferir se a mensagem de erro é compreensível — simulado em 27/10 (pedido de link do `cloudflared` sem resposta): em 0,7 s aparece "Não foi possível criar o link. Verifique sua conexão com a internet e tente novamente."; vale repetir com o Wi-Fi desligado de verdade
- [x] (Se o áudio entrar) tocar um vídeo, falar no Discord e confirmar que os espectadores não ouvem a call — validado em 27/10 com uma call real

### Riscos específicos do prazo

| Risco | Plano |
|---|---|
| `aiortc` + `windows-capture` levarem mais que 2 dias | Na terça à noite, se ainda não funcionar localmente, cortar a janela para uma tela única com um botão Começar/Parar |
| Instabilidade do `trycloudflare.com` no dia do teste | Ter o `--no-tunnel` em rede local como plano B da sessão |
| Áudio atrasar o resto | Áudio é meta extra, com prazo de decisão na quarta à noite |
| Qt + `asyncio` congelar a janela | Se o `qasync` der problema, rodar o núcleo em uma thread com loop próprio e conversar com a janela por sinais do Qt |

---

## 🚀 Alternativa: versão 1.0 completa até quinta-feira (29/10/2026, 23:59)

Cenário alternativo ao Marco 1, partindo do princípio de que daria tempo de fazer **todas as Fases de 0 a 9** até quinta à meia-noite. A Fase 10 continua depois da 1.0.

### Regras para ordenar o trabalho

1. **Fazer primeiro o que é arriscado.** Captura de vídeo + `aiortc` e o áudio em C++ são as partes que podem dar errado. Se derem, ainda sobra tempo para reagir.
2. **Ter a transmissão funcionando de ponta a ponta já na segunda.** Uma versão feia, mas completa, vale mais que módulos perfeitos e soltos.
3. **Construir a interface aos poucos, junto com o núcleo.** Desenhar os estados da janela na segunda de manhã ajuda a definir a `StreamSession` do jeito certo.
4. **Testar o empacotamento cedo.** O PyInstaller com `aiortc`, PyAV e PySide6 costuma dar problema de dependências, e isso precisa aparecer na terça, não na quinta à noite.
5. **Parar de adicionar funcionalidades na quinta às 14h.** Daí em diante, só testes, correções e lançamento.

### Ordem dia a dia

| Quando | O que fazer | Fases |
|---|---|---|
| **Seg 26/10, manhã** | Estrutura do repositório, dependências e logging. Em 1 a 2 horas, desenhar os estados da janela e escrever o `messages.py` | 0, 2 (resumida) |
| **Seg 26/10, tarde** | Captura de vídeo, track do `aiortc`, servidor e uma página mínima para quem assiste. Primeira transmissão na rede local | 1 |
| **Seg 26/10, noite** | Começar o `peek-audio.exe`: achar o Discord e gravar o som em um arquivo `.raw` | 4 (início) |
| **Ter 27/10, manhã** | `StreamSession`, modo `--headless` e `cloudflared` com token no link. Transmissão vista de outra rede | 1, 3 |
| **Ter 27/10, tarde** | Terminar o helper de áudio e ligá-lo ao núcleo, com o som sincronizado ao vídeo | 4, 5 |
| **Ter 27/10, noite** | **Teste de empacotamento**: gerar o `.exe` do que já existe e abrir em outra máquina | 9 (antecipada) |
| **Qua 28/10, manhã** | Opções de qualidade, troca durante a transmissão sem reconectar ninguém e medição de FPS/CPU | 6 |
| **Qua 28/10, tarde e noite** | Janela completa: miniaturas, todos os estados, contador, aviso de tela inteira. Página do espectador final | 7, 8 |
| **Qui 29/10, manhã** | Casos de borda: Discord aberto depois, reinício do `cloudflared`, mensagens de erro específicas, aviso de Windows incompatível, reconexão de quem assiste | 3, 5, 7, 8 |
| **Qui 29/10, 14h** | **Parar de adicionar funcionalidades** | — |
| **Qui 29/10, tarde** | `Peek.exe` final, publicação automática no GitHub Actions, teste em máquina limpa e início do teste de 2 horas seguidas | 9 |
| **Qui 29/10, noite** | Teste com alguém que não programa, correções e publicação da versão nas Releases antes de 23:59 | 9 |

Fica para depois da 1.0: a Fase 10, a CI completa com testes de interface e os wireframes detalhados da Fase 2.

### Divisão com duas pessoas

- **Pessoa A (núcleo em Python):** Fases 1 → 3 → 6, depois a integração do áudio (Fase 5).
- **Pessoa B (áudio e interface):** Fase 4 desde segunda à tarde, depois a janela (Fase 7) e a página do espectador (Fase 8). Até a `StreamSession` existir, a janela pode ser feita sobre uma versão falsa dela.
- As duas partes se juntam na **quarta à noite**. Quinta segue igual à tabela.

### Riscos deste cenário

- **Não há folga.** Qualquer travamento de mais de meio dia em áudio ou empacotamento empurra o lançamento para depois de quinta. Nesse caso, voltar ao escopo do **Marco 1**.
- **Não cortar:** a parada de funcionalidades na quinta às 14h e o teste do `.exe` na terça à noite.
- **Depende de outra pessoa:** o teste com alguém que não programa exige uma pessoa disponível na quinta à noite, e isso precisa ser combinado com antecedência.

---

## Premissas

- O desenvolvimento e os testes de quem transmite acontecem em **Windows 11**.
- Grupos pequenos: **até ~4 espectadores** por transmissão (P2P, codificação por software).
- Sem servidor próprio na 1.0: sinalização via `aiohttp` + Cloudflare Tunnel (`trycloudflare.com`), mídia via WebRTC P2P com STUN público.
- A interface segue à risca o **"Princípio do projeto"** do README (no máximo três passos, sem termos técnicos, sem terminal).
- Nomes de módulos seguem a estrutura proposta no README; nomes de classes citados aqui (ex.: `StreamSession`) são **sugestões** e podem mudar.

---

## Fase 0 — Fundação do repositório

**Objetivo:** ter um repositório organizado, reprodutível e com verificações automáticas desde o primeiro commit de código.

- [x] Criar a estrutura de pastas do README (`host/`, `audio-helper/`, `web/`)
- [x] `requirements.txt` com versões fixadas (`PySide6`, `windows-capture`, `aiortc`, `av`, `aiohttp`, `qasync`) e `requirements-dev.txt` (`pytest`, `pytest-asyncio`, `ruff`, `pyinstaller`)
- [x] Configurar `ruff` (lint/format) e `pytest`
- [ ] CI no GitHub Actions em `windows-latest`: lint + testes Python + compilação do `audio-helper`
- [ ] Escolher e adicionar o arquivo `LICENSE`; adicionar `THIRD_PARTY_NOTICES` (licença Apache 2.0 do `cloudflared`)
- [x] `.gitignore` (`.venv`, `build/`, `dist/`, binários em `host/bin/`)
- [x] Logging estruturado em arquivo (`%LOCALAPPDATA%\Peek\logs`) desde o início, já que o usuário final não verá terminal

**Pronto quando:** `python -m host --help` roda e a CI passa em um PR vazio.

---

## Fase 1 — Vídeo local de ponta a ponta

**Objetivo:** provar a parte mais arriscada do núcleo: tela capturada → `aiortc` → navegador, em rede local, sem túnel e sem áudio.

- [x] `capture/video.py`: captura de monitor e de janela com `windows-capture`, entregando frames em uma fila consumível pelo `asyncio` (a biblioteca usa callbacks em outra thread)
- [x] Listagem de monitores e janelas disponíveis (será usada pela interface na Fase 7)
- [x] `rtc/tracks.py`: `VideoStreamTrack` que lê a fila, respeita o FPS alvo e descarta frames atrasados
- [x] `server.py`: `aiohttp` servindo `web/` e um WebSocket de sinalização (oferta/resposta/ICE), **uma `RTCPeerConnection` por espectador**
- [x] `web/` mínimo: página que conecta e exibe o vídeo
- [x] **Camada de controle** `StreamSession` (ex.: `start(source, quality)`, `stop()`, `set_quality()`, eventos `viewers_changed`, `error`, `link_ready`). Tudo que a interface fizer passa por ela — `set_quality()` fica para a Fase 6
- [x] `__main__.py` com `--headless`, `--window`, `--monitor`, `--port`, `--no-tunnel`
- [x] Medir uso de CPU com 1, 2 e 4 espectadores em 720p30 (base para a Fase 6)

  Medição de 26/10 (8 núcleos, tela 1920x1080 com uma área de 800x600 em movimento contínuo, preset Equilibrada, espectadores `aiortc` na mesma máquina, VP8). CPU só do processo do Peek:

  | Espectadores | CPU (% de 1 núcleo) | CPU (% do total) | FPS recebido |
  |---|---|---|---|
  | 0 (só capturando) | 21% | 2,7% | — |
  | 1 | 99% | 12,4% | 29,8 |
  | 2 | 131% | 16,4% | 30,0 |
  | 4 | 177% | 22,1% | ~27 |

  Os espectadores rodavam no mesmo PC e disputavam CPU com o Peek, então os números são aproximados. Com 4 espectadores, o FPS já cai um pouco abaixo de 30. Refazer com espectadores reais na sessão de quinta.

**Pronto quando:** um segundo dispositivo na mesma rede abre `http://<ip>:8080` e vê a tela com latência aceitável.

---

## Fase 2 — Design da interface (UX)

**Objetivo:** definir *antes de codar* como a janela e a página do espectador vão se comportar, garantindo os "três passos" do README. Pode correr em paralelo às Fases 1, 3 e 4.

- [ ] Mapear os estados da janela e as transições:
  1. **Escolher o que mostrar** (grade de miniaturas: telas e janelas)
  2. **Pronto para transmitir** (fonte escolhida, qualidade "Equilibrada", opção **Incluir som** marcada)
  3. **Preparando** (criando link, iniciando áudio, com indicação de progresso)
  4. **Transmitindo** (link + **Copiar link**, contador de espectadores, troca de qualidade, **Parar**)
  5. **Erro** (frase clara + ação sugerida, ex.: **Tentar novamente**)
  6. **Incompatível** (Windows antigo)
- [ ] Wireframes de baixa fidelidade de cada estado (Figma ou papel) e da página do espectador
- [ ] Redigir `gui/messages.py`: todos os textos e mensagens de erro em linguagem do dia a dia, revisados contra a lista de termos proibidos ("bitrate", "WebRTC", "tunnel" etc.)
- [ ] Definir o lembrete breve ao escolher **tela inteira** (notificações ficam visíveis)
- [ ] Definir o comportamento de "Mais opções" → **Personalizada**, escondido por padrão
- [ ] Acessibilidade básica: navegação por teclado, contraste, tamanho de fonte, escala de DPI do Windows
- [ ] Validar os wireframes com 1–2 pessoas que não programam (teste de corredor)

**Pronto quando:** wireframes e textos aprovados; cada estado tem um evento correspondente na `StreamSession`.

---

## Fase 3 — Link público automático

**Objetivo:** gerar um link HTTPS público sem que quem transmite saiba o que é um túnel.

- [x] `tunnel.py`: iniciar `cloudflared` como subprocesso **sem janela de console** (`CREATE_NO_WINDOW`), ler a URL `trycloudflare.com` da saída, com timeout — o link só é entregue depois que o endereço existe no DNS (em 27/10 isso levou ~12 s; antes disso o amigo veria "site não encontrado")
- [ ] Monitorar o processo: detectar queda, tentar reiniciar e emitir evento de erro amigável — detecção e erro (`TUNNEL_LOST`) feitos; reinício fica para depois do Marco 1
- [x] Encerrar o `cloudflared` ao parar ou fechar o Peek (inclusive em fechamento abrupto, via *job object* do Windows)
- [x] **Código da sala**: incluir um token aleatório no caminho do link (ex.: `/s/<token>`) e recusar sinalização sem token válido; invalidar ao parar
- [ ] Endurecer a sinalização: limite de espectadores simultâneos, limite de tamanho de mensagem e de conexões por IP
- [ ] Garantir que a página do espectador **não expõe nenhum controle** de quem transmite
- [x] Testar espectador em outra rede (4G, rede de amigo) — validado em 27/10

**Pronto quando:** `python -m host --headless` imprime um link que funciona fora da rede local, e o link deixa de funcionar ao parar.

---

## Fase 4 — Helper de áudio sem o Discord (C++)

**Objetivo:** capturar todo o áudio do sistema exceto o Discord. Componente independente, pode começar cedo.

- [x] Projeto CMake em `audio-helper/` — compila com MSVC ou llvm-mingw (27/10: llvm-mingw, que não tem o `audioclientactivationparams.h`; as estruturas estão declaradas no `main.cpp`)
- [x] Localizar o `Discord.exe` raiz (pai não é outro `Discord.exe`); considerar também variantes (`DiscordPTB.exe`, `DiscordCanary.exe`)
- [x] `ActivateAudioInterfaceAsync` com `PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE`
- [x] Saída PCM float32 LE, 48 kHz, estéreo no `stdout`, conforme o protocolo do README
- [x] Mensagens de status/erro em `stderr` com formato simples e estável (ex.: `STATUS discord_found pid=...`, `ERROR unsupported_os`) para o Python interpretar
- [x] Modo fallback quando o Discord não está aberto (loopback do sistema inteiro) — exclui só o próprio helper
- [x] Verificação de versão do Windows (build ≥ 20348) com código de saída específico
- [x] Teste manual: tocar música + falar na call do Discord e confirmar que só a música é capturada — validado em 27/10 com uma call real (antes, a exclusão já tinha sido provada com `--exclude-pid`)

**Pronto quando:** `peek-audio.exe > out.raw` gera um arquivo que, reproduzido, não contém o áudio do Discord.

---

## Fase 5 — Áudio integrado ao núcleo

**Objetivo:** levar o áudio do helper até os espectadores, sincronizado com o vídeo e sem intervenção manual.

- [x] `capture/audio.py`: iniciar o `peek-audio.exe` sem console, ler o `stdout` de forma assíncrona e montar frames para o `aiortc`
- [x] `AudioStreamTrack` em `rtc/tracks.py` (Opus via `aiortc`) — `SystemAudioTrack`; em 27/10 um tom de 1 kHz chegou a um espectador `aiortc` com o mesmo volume
- [ ] Ajuste de sincronia áudio/vídeo (timestamps coerentes)
- [ ] **Detecção do Discord aberto depois**: monitorar processos e reiniciar o helper automaticamente, sem derrubar os espectadores
- [ ] Reiniciar o helper se ele cair, com limite de tentativas e mensagem amigável
- [x] Opções `--no-audio` e `--include-discord`
- [x] Expor na `StreamSession` o estado do som (ativo, sem som, erro) — `sound_changed(SoundState)`; se o som falhar, a transmissão segue só com imagem e a janela avisa

**Pronto quando:** espectadores ouvem o jogo/vídeo, não ouvem a call, e abrir o Discord no meio da transmissão não exige nenhuma ação.

---

## Fase 6 — Qualidade e FPS em tempo real

**Objetivo:** implementar as opções da tabela do README com troca instantânea e proteção para PCs mais fracos.

- [ ] `rtc/quality.py`: presets **Econômica, Equilibrada, Nítida, Fluida, Máxima** + **Personalizada**
- [ ] Redimensionamento sem nunca aumentar além do tamanho original
- [ ] Limite de envio por espectador (teto de bitrate no encoder/`RTCRtpSender`)
- [x] Troca de qualidade **sem renegociar** a conexão (alterar FPS/escala na track e o teto no encoder) — `StreamSession.set_quality`; mudar o FPS recria só a captura
- [x] Trocar a tela/janela durante a transmissão sem desconectar ninguém (`StreamSession.switch_source`); se a nova falhar, continua a anterior
- [ ] Medição de FPS real e uso de CPU; emitir evento "PC não está dando conta" com sugestão de opção mais leve
- [ ] Flags `--quality`, `--resolution`, `--fps`, `--bitrate`
- [ ] Testes unitários dos presets e da regra de "não aumentar resolução"

**Pronto quando:** trocar de "Equilibrada" para "Fluida" durante a transmissão muda a imagem em poucos segundos sem desconectar ninguém.

---

## Fase 7 — Janela do Peek (PySide6)

**Objetivo:** implementar a interface desenhada na Fase 2 sobre a `StreamSession`. É a fase que transforma o núcleo em produto.

**Arquitetura**

- [ ] Integrar o loop do Qt com o `asyncio` (`qasync`), mantendo a captura e a codificação fora da thread da interface
- [ ] A janela só conversa com a `StreamSession` (sinais/eventos), nunca com `aiortc` ou `cloudflared` diretamente

**Telas e componentes**

- [ ] Grade de **miniaturas** de telas e janelas, com atualização periódica e nomes legíveis
- [ ] Seletor de qualidade com os nomes do dia a dia e uma frase curta ("Para jogos com bastante movimento")
- [ ] Caixa **Incluir som** (marcada por padrão)
- [ ] Botão **Começar a transmitir** → estado "Preparando" com progresso
- [ ] Estado "Transmitindo": link visível, **Copiar link** com confirmação ("Link copiado!"), **contador de pessoas assistindo**, troca de qualidade, **Parar**
- [ ] Lembrete breve ao escolher tela inteira
- [ ] Telas de **erro** usando `gui/messages.py`, sempre com uma ação (ex.: **Tentar novamente**)
- [ ] Tela de **Windows incompatível** antes de qualquer outra coisa
- [ ] Confirmação ao fechar a janela durante uma transmissão
- [ ] Ícone, nome e identidade visual mínimos; suporte a tema claro/escuro do Windows e escala de DPI
- [ ] Lembrar a última fonte e qualidade escolhidas (configuração local)

**Qualidade**

- [ ] Testes de interface com `pytest-qt` para os fluxos principais (iniciar, copiar, trocar qualidade, parar, erro)
- [ ] Revisão de todos os textos contra os termos técnicos proibidos

**Pronto quando:** é possível transmitir em três passos usando só a janela, sem terminal, cobrindo todos os estados definidos na Fase 2.

---

## Fase 8 — Página do espectador final

**Objetivo:** experiência de quem assiste tão simples quanto a de quem transmite.

- [x] Layout limpo, sem rolagem, tela cheia (botão, duplo clique ou tecla F), controle de volume (lembra o último volume) — em React, 26/10
- [ ] Aviso **"Clique para ativar o som"** quando o navegador bloquear o autoplay
- [ ] Indicador discreto da qualidade atual (ex.: "Nítida")
- [ ] Estados claros: "Conectando…", "A transmissão terminou", "Não foi possível conectar. Tente outro navegador ou outra rede."
- [ ] Reconexão automática em quedas curtas
- [ ] Teste em Chrome, Edge e Firefox (desktop) e verificação básica em celular — desktop validado em 27/10; falta o celular
- [ ] Sem dependências externas de CDN (tudo servido localmente)

**Pronto quando:** um amigo abre o link e assiste sem precisar de instruções além de "clique se não tiver som".

---

## Fase 9 — Empacotamento, testes e lançamento 1.0

**Objetivo:** entregar um único `Peek.exe` confiável e validar o princípio de simplicidade com usuários reais.

**Empacotamento**

- [ ] `peek.spec` do PyInstaller: arquivo único, modo janela (sem console), embutindo `peek-audio.exe`, `cloudflared.exe` e `web/`
- [ ] Resolução de caminhos de recursos que funcione tanto em desenvolvimento quanto no `.exe`
- [ ] Metadados do executável (versão, ícone, nome do produto)
- [ ] Pipeline de release no GitHub Actions: build do helper + build do `.exe` + publicação nas Releases com checksum SHA-256
- [ ] Verificar o `.exe` em uma máquina Windows 11 limpa (sem Python, sem Visual Studio)

**Testes e validação**

- [ ] Matriz de testes manuais: monitor único/múltiplos, janela minimizada/redimensionada, Discord aberto antes/depois/não aberto, 1–4 espectadores, redes diferentes
- [ ] Teste de longa duração (≥ 2 h) observando memória, CPU e estabilidade do túnel
- [ ] **Teste com alguém que não programa:** transmitir do zero, sem ajuda, em menos de 2 minutos. Registrar onde a pessoa hesitou e corrigir
- [ ] Revisar o README (substituir `<seu-usuario>`, atualizar status e roadmap)

**Pronto quando:** o `Peek.exe` está publicado e o teste com quem não programa foi aprovado.

---

## Fase 10 — Depois da 1.0

Itens do roadmap do README, a priorizar com base no retorno de uso:

- [ ] Suporte opcional a servidor TURN (para redes restritivas)
- [ ] Sugestão automática de qualidade conforme PC e internet
- [ ] Estudo de encoder por hardware (GStreamer `webrtcbin`) para reduzir CPU
- [ ] Assinatura de código do executável (reduz avisos do SmartScreen e antivírus)
- [ ] Atualização automática / aviso de nova versão

---

## Riscos e mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| CPU alta com codificação por software (`aiortc`), uma por espectador | Jogo travando, transmissão ruim | Medir já na Fase 1; padrão "Equilibrada"; aviso automático (Fase 6); estudo de encoder por hardware (Fase 10) |
| Integração Qt + `asyncio` + threads de captura | Interface congelando | Definir a arquitetura (`qasync`, filas) no início da Fase 7; nunca processar frames na thread da interface |
| API de *Application Loopback* com comportamento diferente entre builds do Windows | Áudio do Discord vazando ou sem áudio | Testar em mais de uma máquina; fallback e mensagens claras (Fase 4) |
| Links `trycloudflare.com` sem garantia de disponibilidade | Link não é criado | Timeout + nova tentativa + mensagem amigável; avaliar alternativa no pós-1.0 |
| NAT restritivo impedindo P2P | Amigo não consegue assistir | Mensagem clara no espectador; TURN opcional (Fase 10) |
| Falsos positivos de antivírus/SmartScreen no `.exe` do PyInstaller | Usuário desiste de abrir | Orientação no README; checksum nas Releases; assinatura de código no pós-1.0 |
| Link vazado permite que estranhos assistam | Privacidade | Token aleatório no link, invalidação ao parar, limite de espectadores (Fase 3) |
| Interface acumular termos técnicos ao longo do desenvolvimento | Quebra o princípio do projeto | Textos centralizados em `messages.py` e revisão em cada PR de interface |

---

## Próximos passos imediatos

1. Escolher entre o **Marco 1** (versão testável, escopo reduzido) e a **Alternativa** (versão 1.0 completa) até quinta (29/10/2026). No Marco 1, CI, licença e wireframes completos (Fase 2) ficam para a semana seguinte.
2. Depois da sessão de teste de quinta, revisar este plano com os números reais de CPU e latência e com os problemas encontrados.
3. Retomar as fases normais pela parte que ficou de fora do Marco 1, priorizando áudio (se não entrou), troca de qualidade em tempo real e `Peek.exe`.

> Este plano é um ponto de partida e deve ser revisado ao final de cada fase.
