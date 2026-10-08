# Hướng dẫn `codex-room-setup`

Tài liệu này giải thích cách bộ setup tạo một phòng gồm ba vai trò trên ba
runtime (Codex, Claude Code, oh-my-pi) và cách các vai trò phối hợp để hoàn
thành một outcome kỹ thuật.

## Bức tranh tổng thể

```text
Paseo provider codex-<role>
    -> ~/.local/bin/codex-room <role>
    -> codex-room-sync <role>
    -> ~/.codex-runtime/<role>/config.toml
    -> Codex với CODEX_HOME riêng

Paseo provider claude-<role> | omp-<role>
    -> ~/.local/bin/agent-room <claude|omp> <role>
    -> claude / omp của operator (home và login gốc) + chỉ dẫn role
```

Mỗi runtime có ba provider: `<runtime>-supervisor`, `<runtime>-lead`, và
`<runtime>-peer` (runtime là `codex`, `claude`, hoặc `omp`). Supervisor và Lead
nhận Paseo tools; Peer không nhận công cụ điều phối.

## Ranh giới trách nhiệm

- Human giữ mục tiêu sản phẩm, ưu tiên, chi phí vật chất, tác động bên ngoài,
  và quyết định rủi ro không thể đảo ngược.
- Supervisor quan sát workspace, chuyển nguyên vẹn chỉ thị của Human, và thực
  hiện phục hồi vận hành có giới hạn. Supervisor không trở thành Lead thứ hai.
- Lead giữ quyết định kỹ thuật của một dự án, dependency order, tích hợp,
  kiểm chứng, và quyết định chấp nhận candidate.
- Peer nhận đúng một outcome có giới hạn. Peer có thể triển khai, điều tra,
  đưa ra ý kiến kiến trúc, hoặc kiểm tra candidate trong phạm vi được giao.

Lead chạy tối đa 3 Peer ghi song song, và chỉ khi mỗi Peer có input đã được
chấp nhận và write scope (Touches) riêng, không giao nhau; nếu không thì làm
tuần tự. Peer được commit file của mình trên branch hiện tại (không push,
merge hay deploy) trừ khi Human cấm commit. Peer có
thể gửi `REOPEN_REQUEST` khi tiền đề kỹ thuật thất bại,
`DEPENDENCY_REQUEST` khi thiếu prerequisite chưa có owner, hoặc `BLOCKED` khi
không còn bước an toàn trong phạm vi. Mỗi tín hiệu cần nêu bằng chứng, hệ quả,
và quyết định cần có.

Khi một quyết định kiến trúc hoặc candidate có rủi ro đủ lớn, Lead có thể gọi
một Peer mới ở chế độ chỉ đọc để xem đúng candidate hoặc snapshot đã cố định.
Đây vẫn là Peer theo nhiệm vụ, không tạo thêm provider hay cấp bậc mới.

## Chạy ticket theo spec (spec-orchestration)

Khi Human giao cho Lead một thư mục spec có `spec.md` và `issues/NN-*.md`, Lead
làm theo `~/.config/codex-room/skills/spec-orchestration/SKILL.md`:

- Lead không sửa code. Lead chỉ ghi header và `## Comments` của ticket, cùng
  thư mục `<SPEC>/.room/` (baseline, brief, report, review, câu hỏi).
- `frontier.py` chọn ticket sẵn sàng: blocker đã xong, `Touches` không giao
  ticket đang chạy; tối đa 3 Peer cùng lúc trên cùng branch.
- Mỗi ticket (và mỗi lượt sửa lại) giao cho một Peer mới qua công cụ Paseo,
  mặc định cùng runtime với Lead (`claude-lead` → `claude-peer`), hoặc theo
  dòng `Runtime:` của ticket.
- Peer commit bằng pathspec trong lock, lưu log gate và ghi `report.md` với
  `SIGNAL: CANDIDATE | REOPEN_REQUEST | DEPENDENCY_REQUEST | BLOCKED`.
- Lead review theo SHA, kiểm log gate thay vì chạy lại test, rồi ACCEPT/REJECT.
- Không dùng hook chặn lệnh git. `tree-audit.py` phát hiện đổi branch, reset,
  rebase, amend, stash, push, và thay đổi trên file Human đang sửa dở, cho cả
  ba runtime. Nó phát hiện sau khi xảy ra, không ngăn trước: `reset --hard` hay
  `clean` vẫn có thể làm mất thay đổi chưa commit của Peer khác.
- Câu hỏi kỹ thuật Lead tự trả lời; câu hỏi nghiệp vụ Lead hỏi Human trong chat
  và chỉ tiếp tục các ticket độc lập với câu hỏi.

Skill này độc lập với skill `orchestrate` của từng project (ví dụ bản herdr
trong PMS): khác tên, khác thư mục chạy (`.room/` thay vì `.orch/`), và chỉ được
nạp khi Lead chạy trong Paseo.

## Cài đặt và sinh runtime

Luồng public duy nhất là `./install` để xem kế hoạch, `./install --apply` để
cài đặt, sau đó operator khởi động Paseo và chạy `./install --verify`. Các
script thấp hơn chỉ dành cho bảo trì có mục tiêu, không phải một đường cài đặt
thay thế.

`home/` là bản mirror của `$HOME`. `./install --apply` cài overlay, chỉ
dẫn chung, workspace protocol, launcher, và cấu hình Paseo. Script không ghi
vào `~/.codex`.

`codex-room-sync` đọc `~/.codex/config.toml` làm base, áp dụng các scalar được
cho phép trong overlay, ghép chỉ dẫn của role, và sinh `config.toml` cùng model
catalog riêng. Nó luôn tắt native Codex agents để Paseo giữ topology ba vai
trò. Auth, skills và plugins được dùng qua symlink; `hooks.json` là tùy chọn
và chỉ được chia sẻ khi có sẵn. Session, log, state và database vẫn tách theo role.

Generator không cần thêm workflow asset để chạy. Nó không khởi tạo, xóa, hay
ghi đè notebook riêng, session, runtime directory, hoặc byte thuộc `~/.codex`
của operator. Những file cũ còn tồn tại được giữ nguyên nhưng không phải là
dependency của runtime mới.

`agent-room` không sinh home riêng cho Claude Code hay omp: đổi
`CLAUDE_CONFIG_DIR` sẽ đổi khóa Keychain (mất login), còn đổi agent dir của omp
sẽ chuyển cả database credential. Thay vào đó launcher đọc
`developer_instructions` từ cùng overlay của role rồi áp dụng theo từng
process:

- Claude Code: thêm hook `SessionStart` vào `--settings` để nạp chỉ dẫn role
  (kể cả sau resume/compact) và chặn `Agent`, `Workflow` bằng
  `--disallowedTools`.
- omp: nạp `~/.config/codex-room/omp-room.config.yml` bằng `--config`
  (`task.maxRecursionDepth: 0` gỡ tool `task`) và gộp chỉ dẫn role với
  `--append-system-prompt` mà Paseo truyền vào.
- Các lệnh probe như `--version` hoặc `auth status` chạy nguyên trạng.

Model, thinking và permission mode của Claude/omp do Paseo agent chọn; các key
chỉ dành cho Codex trong overlay (`model`, `sandbox_mode`, ...) không áp dụng.

## Luồng một candidate

Lead gửi cho Peer outcome quan sát được, dependency, write scope, invariant,
bằng chứng nghiệm thu, và điều kiện cần mở lại quyết định. Peer tự điều tra
trong phạm vi đó, chạy proof phù hợp, rồi trả immutable candidate (commit hoặc
snapshot), base ban đầu, danh sách path, lệnh đã chạy, và rủi ro còn lại.

Lead đọc artifact chính xác và đưa ra quyết định kỹ thuật rõ ràng: chấp nhận
hoặc từ chối, kèm lý do. Test pass, thông báo hoàn thành, và trạng thái
workspace là bằng chứng hỗ trợ; chúng không tự tạo thành acceptance.

Sau khi dispatch, các role chờ event finish, error, attention, hoặc decision.
Không lặp lại truy vấn khi state chưa đổi.

## Các lệnh thường dùng

```bash
# Xem kế hoạch đầy đủ, không ghi filesystem
./install

# Cài đặt đầy đủ với transaction/rollback
./install --apply

# Kiểm tra installed và live provider (daemon phải đang chạy)
./install --verify

# Kiểm tra source, không cần runtime đã cài
./scripts/verify --source

# Chạy test của repository
make test
```

Sau khi thay provider catalog trong `home/.paseo/config.json.template`, chạy
`make test`, `./scripts/verify --source`, `./install --apply`, restart Paseo,
rồi chạy `./install --verify` nếu daemon đang hoạt động. Kiểm tra live provider và
MCP là bước vận hành của operator, không được suy ra chỉ từ test source.

## Sửa ở đâu?

- Đổi model hoặc authority của role: sửa overlay tương ứng (authority áp dụng
  cho cả ba runtime; model chỉ áp dụng cho Codex).
- Đổi provider, command, hoặc MCP boundary: sửa
  `home/.paseo/config.json.template`.
- Đổi cách ghép config Codex: sửa `home/.local/bin/codex-room-sync`; đổi cách
  áp role cho Claude/omp: sửa `home/.local/bin/agent-room`. Cập nhật test
  boundary tương ứng.
- Đổi nguyên tắc phối hợp chung: sửa
  `home/.config/codex-room/workflow/WORKSPACE_PROTOCOL.md`.

Không sửa trực tiếp `~/.codex-runtime/<role>/config.toml`; đó là output được
sinh lại. Không đưa auth, session, log, database, keypair, token, hay private
workspace state vào Git.
