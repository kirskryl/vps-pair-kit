# HOME + EGRESS: baseline v1

Комплект готовит локальные файлы; не является автоматическим installer. Целевая среда — Debian 12/Ubuntu 24.04, systemd, IPv4, нативные приложения. Версия sing-box должна быть одинаковой на обоих узлах и зафиксирована оператором до установки. Runtime совместимость и реальная связность считаются доказанными только после приёмки ниже; этот комплект сам ничего не устанавливает и не выполняет SSH.

## Договорённости и безопасный сбор данных

HOME хранит приложения и данные. EGRESS обслуживает только зашифрованный транспорт. На HOME один sing-box mixed на `127.0.0.1:PROXY_PORT`; весь переданный ему HTTP CONNECT/SOCKS TCP трафик (в том числе неизвестные домены и обращения по IP) направляется единственным SS2022 outbound на EGRESS. На EGRESS SS inbound расшифровывает трафик и выпускает его в интернет. `direct` на EGRESS — необходимый выход транспорта; HOME direct/fallback/urltest отсутствуют. SS2022 ключ даёт аутентификацию и шифрование. Пароль произвольной длины для выбранного метода не подходит.

В чате агент спрашивает только несекретные решения: OS, провайдер/регион, имена приложений, нужен ли Docker, окно обслуживания, разрешение на серверные изменения. IP, SSH usernames/paths и ключ транспорта вводятся локально. **Никогда не просить и не отправлять в чат приватные ключи, пароли, API-токены, SS2022 key и SSH host keys. Не вставлять их в shell-команды/history, аргументы процессов, stdout, скриншоты, логи или git.** SSH private key остаётся в исходном защищённом файле: kit получает только абсолютный путь к нему. Host key проверяется локально по доверенной консоли провайдера, не через чат.

**Агент делает сам на доверенном локальном компьютере с Python 3.9+:**

```sh
python3 scripts/kit.py init --open
python3 scripts/kit.py check
python3 scripts/kit.py render
python3 -m unittest discover -s tests -v
```

Владелец не запускает эти команды. Агент сначала ищет уже известные данные в конфигурации этого проекта и локальном SSH config, но не угадывает роли VPS по чужим aliases и не читает содержимое приватных ключей. Если данных нет, агент открывает владельцу локальный `.env` и простыми словами объясняет только незаполненные поля. После сохранения файла агент **сам** запускает `check`, исправляет ошибки вместе с владельцем через локальный редактор, затем `render` и тесты. Если владелец не предоставил HOME/EGRESS IP или доступ, агент оставляет состояние «ожидает данные» и не создаёт фиктивные рабочие конфиги. Ошибки и вывод не должны содержать значений ключей. Серверные изменения — отдельный этап по согласованию.

`init` без `--open` только создаёт `.env` с mode 0600 и генерирует ключ SS2022 из 32 случайных байтов. Повторный init сохраняет существующий файл и ключ. `--open` явно открывает локальный редактор (`VISUAL`, `EDITOR`, иначе macOS TextEdit / Linux vi); проверьте, что выбранный редактор не синхронизирует файлы в облако, не сохраняет общедоступные backup/swap. Ничего не вводите через `export`, `source .env`, `echo secret` и CLI flags. Формат `.env`: `NAME=value`, без кавычек, shell substitutions и multiline. `check` сообщает только имена некорректных полей. SS key можно заменить локально на канонический base64 ровно 32 bytes. Скрипт не читает содержимое SSH private keys, проверяет лишь отдельные пути и права. Ключи разных ролей должны иметь разные пути; оператор проверяет, что это разные key pairs.

Результат — новая `.rendered/generation-*` (0700), файлы 0600: `home.json`, `egress.json`, `proxy.env`, `ssh-config`. Каталог и `.env` исключены из git. Нельзя размещать kit внутри синхронизируемой публичной папки. Результат содержит SS secret: не прикладывать его к отчётам. Не распечатывать конфиги и ошибки демона в чат. Не использовать шаблоны с `__PLACEHOLDER__` непосредственно на сервере.

## Границы baseline

Это explicit proxy для TCP. Приложение обязано поддерживать и использовать заданный proxy; environment variables сами по себе не гарантируют, что SDK соблюдает политику. Для SOCKS клиент должен использовать `socks5h` (удалённый DNS), а не `socks5`; HTTP CONNECT передаёт hostname через транспорт. Используйте реальные app session/SDK проверки, не только curl. Убедитесь, что библиотека не делает direct fallback и использует timeout/backoff. Приложения, способные игнорировать proxy, требуют отдельной сетевой изоляции/egress firewall по UID: без неё комплект не гарантирует fail-closed всего хоста. Отрицательный smoke проверяет именно проксируемый путь.

Docker, TUN, UDP, IPv6 egress, multi-egress, Dante, raw SOCKS между VPS и HOME direct вне v1. Не добавлять bridge listener или `0.0.0.0` mixed. Для Docker нужен отдельный согласованный профиль с gateway discovery, firewall, auth/изоляцией контейнеров и отрицательными тестами. Loopback mixed доступен всем локальным пользователям HOME: baseline только для доверенного single-tenant HOME. На multi-tenant HOME нужна отдельная auth/изоляция.

## Preflight до изменения серверов

1. Согласовать окно и доступ через консоль провайдера. Проверить backup/recovery обоих узлов. Зафиксировать существующий unit, binary version/checksum, config, firewall и SSH настройки, активные listeners и правила. Backup содержит secret: root-only 0700/0600, без git и чата.
2. Убедиться в Debian/Ubuntu/systemd, архитектуре CPU и доступности фиксированной версии sing-box. Устанавливать только из официального подписанного package repository с проверкой подписи; запрет `curl | sh`, плавающего `latest` и неподтверждённого бинарника. Путь unit `/usr/bin/sing-box` сверить с пакетом. Сохранить предыдущий пакет для rollback. Здесь версия намеренно не объявлена runtime-tested: выбранную версию записать в канон и выполнить `sing-box check` обоих render outputs. Если проверки нет — остановиться.
3. Проверить, что EGRESS_IP действительно назначен интерфейсу EGRESS (`ip -4 addr`). Для provider NAT публичный адрес может отсутствовать на интерфейсе: этот шаблон тогда неприменим, нужен отдельный private bind/NAT mapping профиль. HOME_IP должен совпадать с фактическим публичным source IPv4 HOME (учесть NAT).
4. Выделить порты и serial deployment lock на обоих узлах (например `flock` на `/run/lock/vps-pair-deploy.lock` внутри maintenance session). До первой установки вывод обеих команд должен быть **пуст**, exit status 0 сам по себе не доказывает свободный порт:

```sh
ss -H -ltn 'sport = :7890'
ss -H -lun 'sport = :7890'
ss -H -ltn 'sport = :8388'
ss -H -lun 'sport = :8388'
```

Заменить числа выбранными `PROXY_PORT` (HOME) / `SS_PORT` (EGRESS). На повторной установке проверить PID/unit каждого существующего listener; не останавливать чужой сервис. Резервирование — [`PORTS.md.template`](vps-pair/templates/PORTS.md.template).
5. Создать по отдельному admin user на каждом хосте, по отдельному SSH key pair с passphrase и локальными правами 0600; публичные ключи установить через доверенный bootstrap/консоль. HOME/EGRESS admins не должны быть app users. Не выдавать app users sudo и не добавлять admin в service groups. Проверить новую key-only сессию и контролируемый sudo в отдельном терминале до ограничения старого доступа. Не менять одновременно SSH port и firewall без recovery. Для каждого VPS отдельно ввести фактический SSH порт в `.env`: `HOME_SSH_PORT` и `EGRESS_SSH_PORT` (по умолчанию оба 22). Если порты отличаются, задать каждый независимо до render. Не путать port render с фактической настройкой sshd.
6. Host fingerprint сверить локально с консолью; только после этого подготовить known_hosts. `ssh-keyscan` без доверенного сравнения не подтверждает подлинность. `StrictHostKeyChecking yes`, отдельные aliases, `ForwardAgent no`. Root — только bootstrap; ограничить/отключить root/password login после подтверждённого admin+sudo+console recovery. Не отключать доступ вслепую.
7. Firewall: сохранить SSH management source/port и established/reply traffic. На EGRESS разрешить TCP SS_PORT только от HOME public IPv4 `/32`, запретить прочим источникам и закрыть UDP/IPv6 на этом порту; разрешить EGRESS исходящие TCP к реальным API и DNS resolver. На HOME смешанный proxy не открывать извне; исходящий SS TCP только на EGRESS. Порядок/команды зависят от текущего nftables/UFW/cloud firewall: не flush rules, не публиковать универсальный replacement ruleset. Проверить и host, и provider firewall.

## Установка после отдельного разрешения владельца

Эти действия выполняет оператор на узлах; локальный helper их не исполняет.

- Создать системного пользователя `pairproxy` без login shell/home и без sudo. Каталог `/etc/vps-pair` root:pairproxy 0750. Установить соответствующий `home.json` или `egress.json` как `/etc/vps-pair/config.json` root:pairproxy 0640 (запись только root). Не использовать world-readable временный файл. Передавать файлы через аутентифицированный SSH с проверенными host keys в admin-owned 0700 staging, оттуда `sudo install` с указанными владельцами/правами; удалить staging после установки.
- `vps-pair-proxy.service.template` устанавливается как `/etc/systemd/system/vps-pair-proxy.service` root:root 0644. Он работает без root/capabilities на высоком порту (PROXY_PORT/SS_PORT ≥1024; HOME_SSH_PORT/EGRESS_SSH_PORT допускают 22). Не заменять пакетный `sing-box.service` и не держать второй процесс на том же порту; discovery должен установить, какой unit уже использует sing-box.
- До reload/start проверить конфиг командой от имени service user, сохраняя вывод только в защищённый локальный файл: `sudo -u pairproxy /usr/bin/sing-box check -c /etc/vps-pair/config.json`. Не выкладывать stderr: ошибки могут содержать credentials. Любая ошибка — STOP и rollback.
- `systemd-analyze verify /etc/systemd/system/vps-pair-proxy.service`; затем daemon-reload, enable/start только нового согласованного unit. Проверить `systemctl is-active vps-pair-proxy`, listener PID/address и права конфига. HOME должен иметь только `127.0.0.1:PROXY_PORT`, EGRESS — выбранный локальный IPv4:SS_PORT и только TCP.
- App user отдельный для каждого приложения; создать `/opt/APP/data` с владельцем app user и 0700 **до** запуска app unit. Код/venv root-owned, приложение не может менять свой код. Создать app-specific proxy env `/etc/APP/proxy.env` и `/etc/APP/app.env` root:root 0600, parent root:root 0700; systemd читает их до смены User. Использовать обязательные EnvironmentFile из bot template. Значения API tokens вводятся только локально/через защищённый secret store. Не задавать `NO_PROXY` для TG/LLM.
- Перенести существующий bot token без второго polling. Для каждой app записать владельца, порт loopback, unit, volume/quota, timeout/retry, реальный API endpoint и health policy в канон. Web apps/DB наружу не открывать; HTTPS ingress HOME организуется отдельно.

## Приёмка и отрицательные проверки

Выполнять сначала на disposable staging с отдельным тестовым ботом, затем в согласованное окно. Не заявлять «работает» только по JSON parsing или unit active.

1. Сверить runtime версии обоих sing-box, выполнить оба `check`, unit verify и права/владельцев. Записать факт PASS/FAIL без конфигов/секретов.
2. Через HOME proxy выполнить `curl --silent --show-error --fail --max-time 15 --noproxy '' --proxy http://127.0.0.1:7890 https://api.ipify.org` и сравнить IPv4 локально с EGRESS public IP. Ответ HOME IP — FAIL. Проверьте правила использования выбранного IP endpoint либо используйте собственный доверенный HTTPS endpoint. Значения IP в чат не обязательны.
3. Проверить HTTP CONNECT реального дополнительного LLM hostname через тот же proxy; выбранный route не зависит от domain allowlist. Выполнить реальный минимальный LLM запрос выбранной модели из действующего SDK/app session; API key брать из secret store, не CLI URL/flags. Ожидаемый статус и response schema задать для конкретного провайдера; root URL с 404 не проверяет API.
4. В единственной действующей bot session выполнить `getMe` через настроенный proxy, проверить `ok:true` и ожидаемый bot id локально. Токен никогда не помещать в curl URL/history или лог. Не запускать второй polling/вторую рабочую session. Отправить/получить тестовое сообщение, если это отдельно разрешено.
5. Отрицательный тест: в согласованном staging остановить **только EGRESS `vps-pair-proxy`** либо временно заблокировать HOME→EGRESS TCP отдельным обратимым firewall правилом. Повторить IP endpoint, TG getMe и LLM через реальную app session с bounded timeout: все должны завершиться ошибкой, без direct fallback. Не останавливать SSH/firewall целиком. Если SDK продолжает работать direct — FAIL; запретить release до app isolation/config fix. Восстановить EGRESS/правило сразу и подтвердить восстановление запросов.
6. Из постороннего source IP SS_PORT должен быть недоступен; с HOME TCP достижим, но с другим временным SS key приложение не должно получить ответ. На HOME с другого узла mixed port недоступен. Проверить cloud/host IPv4+IPv6 firewall. Не помещать неправильный/правильный ключ в CLI аргументы.
7. Рестарт HOME proxy: app requests bounded-fail и затем восстанавливаются. Проверить reboot обоих узлов по одному, proxy/app auto-start, отсутствие второго polling и повторить положительные smoke. Логи проверять локально с redaction; не копировать raw journal в чат.

Health/операции: alert по реальному API успеху и timeout/error rate, FD/CPU/RAM/disk, bounded journal retention, квоты app data; backup конфигов зашифрован вне узла и проверен restore. HOME proxy и EGRESS — отдельные единичные точки отказа; v1 не обещает HA.

## Rollback

До каждого изменения сохранить root-only snapshot конфигов, units, exact package version, firewall и sshd; сохранить отдельную открытую admin/console session. При ошибке не включать direct и не возвращать plaintext transport.

1. Остановить только новый/изменённый `vps-pair-proxy` и app если они не проходят smoke; приложение оставлять fail-closed.
2. Восстановить предыдущую **безопасную** проверенную пару configs и unit/binary version с теми же секретными правами. Если такой пары нет (миграция с raw SOCKS) — оставить proxy/apps остановленными и исправить причину, не откатывать к небезопасному каналу.
3. Выполнить config check + unit verify, daemon-reload, старт, положительный/отрицательный smoke. Удалить только добавленные в этом change firewall rules по сохранённым handles; не flush. SSH изменения откатывать через сохранённую сессию/консоль, проверить доступ перед закрытием сессии.
4. Если secret был раскрыт — не использовать его повторно: отдельно согласовать ротацию SS ключа на обоих узлах и invalidation утёкшего материала. Локальные поколения и backup содержат секреты, хранить 0700/0600 и удалять по retention policy; удаление файла не гарантирует стирание с SSD/backups.

Источники схемы: [SS inbound](https://sing-box.sagernet.org/configuration/inbound/shadowsocks/), [SS outbound](https://sing-box.sagernet.org/configuration/outbound/shadowsocks/), [mixed](https://sing-box.sagernet.org/configuration/inbound/mixed/). Совместимость выбранного бинарника проверяется локально, ссылки не заменяют runtime приёмку.
