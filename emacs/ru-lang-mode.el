;;; ru-lang-mode.el --- Editing support for the 如 language -*- lexical-binding: t; -*-

;; Version: 0.11.1
;; Package-Requires: ((emacs "28.1"))
;; Keywords: languages
;; URL: https://github.com/uppet/ru-language

;;; Commentary:

;; A dependency-free major mode for ru-language 0.11.x source files.  The
;; lightweight lexer mirrors rulang/frontend.py; it deliberately accepts
;; incomplete input.  It is an editing aid, not a compiler or language server.
;; See README.md in this directory for loading, indentation and navigation.

;;; Code:

(require 'cl-lib)
(require 'imenu)
(require 'seq)
(require 'comint)
(require 'compile)
(require 'subr-x)

(defgroup ru-lang nil "Editing the 如 language." :group 'languages)

(defcustom ru-lang-indent-offset 4
  "Number of spaces for each 如 block or bracket nesting level."
  :type 'natnum :safe #'natnump :group 'ru-lang)

(defconst ru-lang--bundled-cli
  (expand-file-name "../ru" (file-name-directory
                             (or load-file-name buffer-file-name)))
  "CLI shipped alongside this copy of the mode.")

(defcustom ru-lang-run-command nil
  "Interpreter command and arguments, before `run' and the source filename.
Nil uses python3 -u and the CLI shipped alongside this mode.  Set this to
an argument list of program, flags and CLI path when
installing the mode separately.  Arguments are passed directly, without a
shell; do not add shell quotes.  Relative paths use the source directory."
  :type '(choice (const :tag "Bundled CLI (python3)" nil)
                 (repeat string))
  :group 'ru-lang)

(defun ru-lang--run-buffer-name (file)
  "Return the output buffer name for absolute source FILE."
  (format "*Ru: %s*" file))

(defconst ru-lang--diagnostic-regexp
  "^\\(.+?\\):\\([1-9][0-9]*\\)\\(?::\\([1-9][0-9]*\\)\\)?: \\(?:error: \\)?\\(.+\\)$"
  "Ru CLI diagnostic with a real filename and one-based codepoint column.")

(defun ru-lang--enable-run-diagnostics (start)
  "Add diagnostic navigation to Comint, starting at this run's START."
  (compilation-shell-minor-mode 1)
  (setq-local compilation-error-regexp-alist
              (list (list ru-lang--diagnostic-regexp 1 2 3 2)))
  (setq-local compilation-error-screen-columns nil)
  (setq-local compilation-first-column 1)
  (setq-local compilation-transform-file-match-alist
              (copy-sequence compilation-transform-file-match-alist))
  (cl-pushnew '("\\`rushu://" nil) compilation-transform-file-match-alist :test #'equal)
  (cl-pushnew '("\\`<" nil) compilation-transform-file-match-alist :test #'equal)
  ;; `compilation-next-error' searches after this position.  Keep it on
  ;; the run header's newline so an immediate first diagnostic is included.
  (setq-local compilation-messages-start
              (if (> start (point-min)) (copy-marker (1- start)) start))
  (setq-local compilation-current-error nil))

;;;###autoload
(defun ru-lang-run-file ()
  "Save if needed and asynchronously interpret the current visited file.
Ask before saving modifications; declining cancels execution.  Output and
errors appear in a per-file Comint buffer, where RET sends input, C-c C-d
sends EOF and C-c C-c interrupts.  A live run is never replaced.  Run from
the source directory, passing filenames directly without a shell."
  (interactive)
  (unless buffer-file-name
    (user-error "This buffer does not visit a file; save it first"))
  (when (file-remote-p buffer-file-name)
    (user-error "Running remote Ru files is not supported"))
  (let* ((file (expand-file-name buffer-file-name))
         (default-directory (file-name-directory file))
         (name (ru-lang--run-buffer-name file))
         (existing (get-buffer name))
         (command (or ru-lang-run-command
                      (list "python3" "-u" ru-lang--bundled-cli))))
    (when (and existing (comint-check-proc existing))
      (display-buffer existing)
      (user-error "This file is already running; interrupt it in %s first" name))
    (unless (and (consp command) (cl-every #'stringp command)
                 (not (string-empty-p (car command))))
      (user-error "Set ru-lang-run-command to a nonempty argument list"))
    (unless (executable-find (car command))
      (user-error "Cannot find %s; customize ru-lang-run-command" (car command)))
    (when (and (null ru-lang-run-command)
               (not (file-readable-p ru-lang--bundled-cli)))
      (user-error "Bundled ru CLI not found; customize ru-lang-run-command"))
    (when (buffer-modified-p)
      (unless (y-or-n-p "Save this file before running it? ")
        (user-error "Run canceled; file was not saved"))
      (save-buffer)
      (when (buffer-modified-p)
        (user-error "File is still modified; run canceled")))
    (unless (file-readable-p file)
      (user-error "Source file is not readable: %s" file))
    (let ((output (get-buffer-create name))
          (default-directory (file-name-directory file))
          (run-start nil)
          (process-connection-type nil)
          (coding-system-for-read 'utf-8-unix)
          (coding-system-for-write 'utf-8-unix))
      (with-current-buffer output
        (setq default-directory (file-name-directory file))
        (let ((inhibit-read-only t))
          (goto-char (point-max))
          (insert (format "\nRunning %s\n" file))
          (setq run-start (copy-marker (point)))))
      (apply #'make-comint-in-buffer "Ru" output (car command) nil
             (append (cdr command) (list "run" file)))
      (with-current-buffer output
        (ru-lang--enable-run-diagnostics run-start))
      (display-buffer output)
      output)))

(defconst ru-lang--keywords
  '("显" "取" "为" "得" "完" "破" "若" "则" "另" "然" "循" "次" "环"
    "算" "作" "法" "其" "且" "或" "非" "空" "对" "形" "象" "如" "新"
    "外言" "尽取" "尽" "卒" "试" "救" "真" "假" "典" "成"))
(defconst ru-lang--types '("数" "句" "阵" "事实" "典" "对" "空" "件" "录" "件作成果" "算" "作"))
(defconst ru-lang--builtins
  '("读" "含" "位" "增" "量" "囫" "囵" "读取" "显出" "错误" "__如竞" "__如观" "__实用"))
(defconst ru-lang--member-builtins '("段" "查" "增" "删" "弹" "排序" "另成" "逐位" "逐目" "量" "读" "写" "在" "除" "列" "词" "数" "行" "清" "三角形" "多边形" "平移" "旋转" "缩放" "保存" "恢复" "变换" "重置变换" "裁剪" "取消裁剪" "颜色" "文字对齐" "经过秒" "间隔秒" "弧" "扇形" "折线" "贝塞尔" "缓存" "贴图")
  "I/O, collection and graphics members highlighted only after a member operator.
The legacy global function 读 is also in `ru-lang--builtins'.")
(defconst ru-lang--pairs '(("算" . "法") ("作" . "为") ("形" . "象")
                            ("若" . "然") ("循" . "环") ("试" . "终") ("典" . "成") ("段" . "落")
                            ("(" . ")") ("[" . "]") ("{" . "}")))
(defconst ru-lang--punctuation
  '((?。 . ".") (?： . ":") (?（ . "(") (?） . ")")
    (?， . ",") (?［ . "[") (?］ . "]") (?｛ . "{") (?｝ . "}")))

(cl-defstruct (ru-lang--token (:constructor ru-lang--make-token))
  text start end kind face)
(cl-defstruct (ru-lang--block (:constructor ru-lang--make-block))
  kind start end name parent header closed literal scoped)

(defvar-local ru-lang--font-lock-face nil)
(defvar-local ru-lang--cache-tick nil)
(defvar-local ru-lang--tokens nil)
(defvar-local ru-lang--blocks nil)
(defvar-local ru-lang--structures nil)
(defvar-local ru-lang--indents nil)
(defvar-local ru-lang--cache-bounds nil)

(defvar ru-lang-mode-syntax-table
  (let ((table (make-syntax-table)))
    (modify-syntax-entry ?_ "w" table)
    ;; Strings and comments receive syntax properties from the lexer.  Generic
    ;; string fences handle curly quotes without letting the other quote close
    ;; a string.  A full rescan also handles edits to multiline strings.
    (dolist (char '(?\' ?\" ?‘ ?’ ?“ ?” ?# ?/ ?。 ?： ?， ?@))
      (modify-syntax-entry char "." table))
    (modify-syntax-entry ?\\ "\\" table)
    (modify-syntax-entry ?（ "(）" table)
    (modify-syntax-entry ?） ")（" table)
    (modify-syntax-entry ?［ "(］" table)
    (modify-syntax-entry ?］ ")［" table)
    (modify-syntax-entry ?{ "(}" table)
    (modify-syntax-entry ?} "){" table)
    (modify-syntax-entry ?｛ "(｝" table)
    (modify-syntax-entry ?｝ ")｛" table)
    table))

(defun ru-lang--name-start-p (char)
  "Whether CHAR can start a name, matching Python's `str.isalpha'."
  (and char (or (= char ?_)
                (memq (get-char-code-property char 'general-category)
                      '(Lu Ll Lt Lm Lo)))))

(defun ru-lang--name-part-p (char)
  "Whether CHAR continues a name, matching Python's `str.isalnum'."
  (and char (or (ru-lang--name-start-p char)
                (memq (get-char-code-property char 'general-category)
                      '(Nd Nl No)))))

(defun ru-lang--comment-marker-p (name)
  "Whether point starts adjacent NAME and punctuation outside a whole name."
  (and (not (ru-lang--name-part-p (char-before)))
       (looking-at (concat name "[.。]"))))

(defun ru-lang--lex ()
  "Return a vector of tokens in the accessible buffer, including trivia."
  (save-excursion
    (goto-char (point-min))
    (let (tokens)
      (while (< (point) (point-max))
        (let ((start (point)) (char (char-after)) kind value)
          (cond
           ((or (looking-at "[[:space:]]+") (= char #xfeff))
            (if (= char #xfeff) (forward-char) (goto-char (match-end 0))))
           ((or (= char ?#) (looking-at "//") (ru-lang--comment-marker-p "批"))
            (end-of-line)
            (setq kind 'comment))
           ((ru-lang--comment-marker-p "解")
            (forward-char 2)
            (unless (re-search-forward "释[.。]" nil t) (goto-char (point-max)))
            (setq kind 'comment))
           ((memq char '(?\' ?\" ?‘ ?“))
            (let ((close (or (cdr (assq char '((?‘ . ?’) (?“ . ?”)))) char)))
              (forward-char)
              (while (and (< (point) (point-max)) (/= (char-after) close))
                (if (= (char-after) ?\\)
                    (forward-char (min 2 (- (point-max) (point))))
                  (forward-char)))
              (when (< (point) (point-max)) (forward-char)))
            (setq kind 'string))
           ((looking-at "\\(?:[0-9]+\\(?:\\.[0-9]+\\)?\\|\\.[0-9]+\\)\\(?:[eE][+-]?[0-9]+\\)?")
            (goto-char (match-end 0)) (setq kind 'number))
           ((ru-lang--name-start-p char)
            (forward-char)
            (while (ru-lang--name-part-p (char-after)) (forward-char))
            (setq kind 'name))
           ((looking-at "[:：]=")
            (forward-char 2) (setq kind 'punct value ":="))
           ((looking-at "==\\|!=\\|<=\\|>=")
            (goto-char (match-end 0)) (setq kind 'punct))
           (t (forward-char) (setq kind 'punct)
              (setq value (cdr (assq char ru-lang--punctuation)))))
          (when kind
            (push (ru-lang--make-token
                   :text (or value (buffer-substring-no-properties start (point)))
                   :start start :end (point) :kind kind)
                  tokens))))
      (vconcat (nreverse tokens)))))

(defun ru-lang--code-token-p (token)
  "Return non-nil if TOKEN contributes to structure."
  (not (memq (ru-lang--token-kind token) '(string comment))))

(defun ru-lang--definition-p (block)
  "Return non-nil when BLOCK is a function, procedure or type."
  (member (ru-lang--block-kind block) '("算" "作" "形")))

(defun ru-lang--literal-header-p (tokens index)
  "Whether 算/作 at INDEX has a complete anonymous header ending in a colon.
Parameters may omit annotations.  Require the colon so a reference
conversion such as 算 名 为 句 remains an expression.
Comments and fullwidth punctuation are accepted."
  (let ((cursor (1+ index)))
    (cl-labels
        ((next-code ()
           (while (and (< cursor (length tokens))
                       (eq (ru-lang--token-kind (aref tokens cursor)) 'comment))
             (setq cursor (1+ cursor)))
           (when (< cursor (length tokens))
             (prog1 (aref tokens cursor) (setq cursor (1+ cursor)))))
         (matches (token text kind)
           (and token (eq (ru-lang--token-kind token) kind)
                (equal (ru-lang--token-text token) text))))
      (let ((token (next-code)))
        (catch 'header
          (when (matches token ":" 'punct) (throw 'header t))
          (while token
            (unless (and (eq (ru-lang--token-kind token) 'name)
                         (not (member (ru-lang--token-text token) ru-lang--keywords)))
              (throw 'header nil))
            (setq token (next-code))
            (when (matches token "为" 'name)
              (setq token (next-code))
              (unless (and token (eq (ru-lang--token-kind token) 'name)
                           (or (not (member (ru-lang--token-text token) ru-lang--keywords))
                               (member (ru-lang--token-text token) '("空" "对" "典" "算" "作"))))
                (throw 'header nil))
              (setq token (next-code))
              (while (matches token "阵" 'name) (setq token (next-code))))
            (when (matches token ":" 'punct) (throw 'header t))
            (when (matches token "," 'punct)
              (setq token (next-code))
              (when (matches token ":" 'punct) (throw 'header t)))))))))

(defun ru-lang--reference-call-ahead-p (tokens index)
  "Recognize named reference calls, ignoring closers of nested definitions."
  (let ((cursor (1+ index)) code)
    (while (and (< cursor (length tokens)) (< (length code) 4))
      (unless (eq (ru-lang--token-kind (aref tokens cursor)) 'comment)
        (push (aref tokens cursor) code))
      (setq cursor (1+ cursor)))
    (setq code (nreverse code))
    (cl-labels ((bare (token)
                 (and token (eq (ru-lang--token-kind token) 'name)
                      (not (member (ru-lang--token-text token) ru-lang--keywords)))))
      (let ((value (nth 3 code)))
        (when (and (bare (nth 0 code)) (bare (nth 1 code))
                   (nth 2 code) (equal (ru-lang--token-text (nth 2 code)) ":")
                   value
                   (or (memq (ru-lang--token-kind value) '(number string)) (bare value)
                       (member (ru-lang--token-text value) '("真" "假" "典" "空" "新" "外言" "其" "非" "(" "[" "{" "+" "-"))))
          (let ((ends (list (if (equal (ru-lang--token-text (aref tokens index)) "算") "法" "为")))
                (previous ":") dot)
            (setq cursor (1- cursor))
            (catch 'complete
              (while (< cursor (length tokens))
                (let* ((token (aref tokens cursor)) (text (ru-lang--token-text token)))
                  (unless (memq (ru-lang--token-kind token) '(comment string))
                    (cond
                     ((and (member text '("算" "作")) (not (equal previous "为"))
                           (ru-lang--literal-header-p tokens cursor))
                      (push (if (equal text "算") "法" "为") ends)
                      (while (not (equal (ru-lang--token-text (aref tokens cursor)) ":"))
                        (setq cursor (1+ cursor))))
                     ((equal text (car ends))
                      (let ((next (1+ cursor)))
                        (while (and (< next (length tokens))
                                    (eq (ru-lang--token-kind (aref tokens next)) 'comment))
                          (setq next (1+ next)))
                        (when (or (not (equal text "为")) (member previous '("." ":"))
                                  (>= next (length tokens))
                                  (not (eq (ru-lang--token-kind (aref tokens next)) 'name)))
                          (pop ends)
                          (unless ends (throw 'complete nil)))))
                     ((and (eq (ru-lang--token-kind token) 'punct) (equal text "."))
                      (setq dot t)))
                    (setq previous text)))
                (setq cursor (1+ cursor)))
              dot)))))))

(defun ru-lang--function-header-p (tokens index allow-incomplete)
  "Classify 算/作 at INDEX as a named header, literal header, or reference.
Return `named' for a declaration at a statement boundary.
Return `literal' for a complete anonymous header, nil for a reference.
ALLOW-INCOMPLETE accepts a partial named header at a statement boundary.
Intervening comments are ignored."
  (let ((cursor (1+ index)) following)
    (while (and (< cursor (length tokens)) (< (length following) 3))
      (unless (eq (ru-lang--token-kind (aref tokens cursor)) 'comment)
        (push (aref tokens cursor) following))
      (setq cursor (1+ cursor)))
    (setq following (nreverse following))
    (let ((name (nth 0 following)) (after (nth 1 following))
          (third (nth 2 following)))
      (cond
       ((ru-lang--reference-call-ahead-p tokens index) nil)
       ((ru-lang--literal-header-p tokens index)
          (if (and allow-incomplete name
                   (eq (ru-lang--token-kind name) 'name)
                   (not (member (and after (ru-lang--token-text after)) '("为" ","))))
              'named
            'literal))
       (t
        (when (or (and allow-incomplete (null name))
                  (and name (eq (ru-lang--token-kind name) 'name)
                       (not (member (ru-lang--token-text name) ru-lang--keywords))
                       (or (and allow-incomplete (null after))
                           (and after (eq (ru-lang--token-kind after) 'punct)
                                (equal (ru-lang--token-text after) ":"))
                           (and after (eq (ru-lang--token-kind after) 'name)
                                (not (member (ru-lang--token-text after) ru-lang--keywords))
                                (or allow-incomplete
                                    (and third (eq (ru-lang--token-kind third) 'name)
                                         (equal (ru-lang--token-text third) "为")))))))
          'named))))))

(defun ru-lang--analyze ()
  "Compute block pairs and desired line depths from `ru-lang--tokens'."
  (let ((tokens ru-lang--tokens) (stack nil) (blocks nil) (structures nil) (indents nil)
        (statement-start t) (line (point-min)) (index 0) previous rescue-binding callable-name
        (next-tokens (make-vector (length ru-lang--tokens) nil)) next-code)
    (cl-loop for i downfrom (1- (length tokens)) to 0 do
             (aset next-tokens i next-code)
             (unless (eq (ru-lang--token-kind (aref tokens i)) 'comment)
               (setq next-code (aref tokens i))))
    (save-excursion
      (while (<= line (point-max))
        (goto-char line)
        (let* ((end (line-end-position)) (depth (length stack))
               (first t) (string-line nil))
          ;; Preserve interior lines of multiline strings and comments,
          ;; including the line containing their closing delimiter.
          (when (and (> index 0)
                     (memq (ru-lang--token-kind (aref tokens (1- index))) '(string comment))
                     (> (ru-lang--token-end (aref tokens (1- index))) line))
            (setq string-line t))
          (while (and (< index (length tokens))
                      (<= (ru-lang--token-start (aref tokens index)) end))
            (let* ((token (aref tokens index))
                   (text (ru-lang--token-text token))
                   (kind (ru-lang--token-kind token))
                   (next (aref next-tokens index))
                   (binding (eq token rescue-binding))
                   (callable-kind (member text '("算" "作")))
                   (callable-type (and callable-kind (equal previous "为")))
                   (definition-start (and callable-kind (not callable-type)
                                          (ru-lang--function-header-p
                                           tokens index statement-start)))
                   (scoped (and (not binding) statement-start
                                (or (equal text "{")
                                    (and (equal text "段") next
                                         (eq (ru-lang--token-kind next) 'punct)
                                         (equal (ru-lang--token-text next) ":")))))
                   (top (car stack))
                   (close (and top (cdr (assoc (ru-lang--block-kind top)
                                              ru-lang--pairs))))
                   (closer (and (ru-lang--code-token-p token)
                                (not binding)
                                (equal text close)
                                ;; 终 is contextual: it is still a legal name
                                ;; and the existing 段 named argument 终:.
                                (or (not (equal text "终")) statement-start)
                                (or (not (equal text "落"))
                                    (and statement-start next
                                         (eq (ru-lang--token-kind next) 'punct)
                                         (equal (ru-lang--token-text next) ".")))
                                (or (not (equal text "为"))
                                    (and (not (ru-lang--block-header top))
                                         (or statement-start
                                             (and first
                                                  (not (and next
                                                            (member (ru-lang--token-text next)
                                                                    ru-lang--types)))))))))
                   (branch (and (ru-lang--code-token-p token) top
                                (not binding)
                                (or (and (equal (ru-lang--block-kind top) "若")
                                         (member text '("则" "另")))
                                    (and (equal (ru-lang--block-kind top) "试")
                                         (equal text "救") statement-start)))))
              (unless (eq kind 'comment)
                ;; A try or rescue header permits an optional colon, but a
                ;; named argument inside its body must not start a statement.
                (when (and top (equal (ru-lang--block-kind top) "试")
                           (ru-lang--block-header top)
                           (not binding) (not branch) (not (equal text ":")))
                  (setf (ru-lang--block-header top) nil))
                (when first
                  (setq depth (max 0 (- (length stack)
                                        (if (or closer branch) 1 0))))
                  (setq first nil))
                (cond
                 (binding
                  (setq rescue-binding nil statement-start t))
                 ((eq kind 'string) (setq statement-start nil))
                 (closer
                  (setf (ru-lang--block-end top)
                        (if (and (not (ru-lang--block-literal top))
                                 (or (ru-lang--block-scoped top)
                                     (not (member (ru-lang--block-kind top) '("(" "[" "{" "典"))))
                                 next (equal (ru-lang--token-text next) "."))
                            (ru-lang--token-end next)
                          (ru-lang--token-end token))
                        (ru-lang--block-closed top) t)
                  (pop stack)
                  ;; Literals and brackets finish expressions.  A following
                  ;; dot belongs to the containing statement, not the literal.
                  (setq statement-start
                        (or (ru-lang--block-scoped top)
                            (and (not (ru-lang--block-literal top))
                                 (not (member (ru-lang--block-kind top) '("(" "[" "{" "典")))))))
                 ((and (assoc text ru-lang--pairs)
                       (or (not (equal text "段")) scoped)
                       (or (not (equal text "典"))
                           (and (not (equal previous "为")) next
                                (eq (ru-lang--token-kind next) 'punct)
                                (equal (ru-lang--token-text next) ":")))
                       (or (not callable-kind) definition-start))
                  (let* ((parent (cl-find-if #'ru-lang--definition-p stack))
                         (name (and (not (eq definition-start 'literal))
                                    (member text '("算" "作" "形")) next
                                    (eq (ru-lang--token-kind next) 'name)
                                    (not (member (ru-lang--token-text next) ru-lang--keywords))
                                    (ru-lang--token-text next)))
                         (block (ru-lang--make-block
                                 :kind text :start (ru-lang--token-start token)
                                 :end (point-max) :name name :parent parent
                                 :literal (or (eq definition-start 'literal) (equal text "典")
                                              (and (equal text "{") (not scoped)))
                                 :scoped scoped
                                 :header (member text '("算" "作" "形" "若" "试" "典" "段")))))
                    (push block stack)
                    (push block structures)
                    (when (or scoped (not (member text '("(" "[" "{")))) (push block blocks)))
                  (setq statement-start (or (and scoped (equal text "{"))
                                            (member text '("循" "试")))))
                 ((or branch (and top (ru-lang--block-header top) (equal text ":")
                                  (member (ru-lang--block-kind top)
                                          '("算" "作" "形" "典" "段" "试"))))
                  (setf (ru-lang--block-header top) nil)
                  (when (and branch (equal text "救") next
                             (eq (ru-lang--token-kind next) 'name)
                             (not (member (ru-lang--token-text next) ru-lang--keywords)))
                    (setq rescue-binding next)
                    (setf (ru-lang--block-header top) t))
                  (setq statement-start (not (equal (ru-lang--block-kind top) "典"))))
                 ((or (equal text ".") (equal text "次"))
                  (setq statement-start (not (and top (equal (ru-lang--block-kind top) "典")))))
                 (t (setq statement-start nil)))
                ;; Set faces on complete lexical names, never keyword substrings.
                (when (eq kind 'name)
                  (setf (ru-lang--token-face token)
                        (cond
                         ((or (and scoped (equal text "段"))
                              (and closer (equal text "落"))) 'font-lock-keyword-face)
                         ((and (equal text "典") (not (equal previous "为")) next
                               (equal (ru-lang--token-text next) ":")) 'font-lock-keyword-face)
                         ((and (equal text "对") top (equal (ru-lang--block-kind top) "典")) 'font-lock-keyword-face)
                         (binding 'font-lock-variable-name-face)
                         ((and closer (equal text "终")) 'font-lock-keyword-face)
                         ((eq token callable-name) 'font-lock-function-name-face)
                         (callable-type 'font-lock-type-face)
                         (callable-kind 'font-lock-keyword-face)
                         ((and (member previous '("@" "其"))
                               (member text ru-lang--member-builtins)) 'font-lock-builtin-face)
                         ((or (member previous '("形" "如" "新"))
                              (and (equal previous "为") (not statement-start))
                              (member text ru-lang--types)) 'font-lock-type-face)
                         ((member text ru-lang--keywords) 'font-lock-keyword-face)
                         ((member text ru-lang--builtins) 'font-lock-builtin-face))))
                (when (and (eq kind 'punct) (equal text ":="))
                  (setf (ru-lang--token-face token) 'font-lock-keyword-face))
                (when (eq token callable-name) (setq callable-name nil))
                (when (and callable-kind (not callable-type)
                           (not (eq definition-start 'literal)) next
                           (eq (ru-lang--token-kind next) 'name)
                           (not (member (ru-lang--token-text next) ru-lang--keywords)))
                  (setq callable-name next))
                (setq previous (unless closer text))))
            (setq index (1+ index)))
          (push (cons line (unless string-line depth)) indents)
          (setq line (1+ end)))))
    (setq ru-lang--blocks (nreverse blocks)
          ru-lang--structures (nreverse structures)
          ru-lang--indents (nreverse indents))))

(defun ru-lang--ensure-cache ()
  "Refresh the lexical and structural cache after text or narrowing changes."
  (unless (and (equal ru-lang--cache-tick (buffer-chars-modified-tick))
               (equal ru-lang--cache-bounds (cons (point-min) (point-max))))
    (setq ru-lang--tokens (ru-lang--lex))
    (ru-lang--analyze)
    (setq ru-lang--cache-tick (buffer-chars-modified-tick)
          ru-lang--cache-bounds (cons (point-min) (point-max)))))

(defconst ru-lang--assignment-help
  "取（词法规则）：函数内先更新当前局部，否则更新最近已有的非模块捕获绑定；未找到则新建当前局部，不隐式改写模块变量。直接救正文中的取写救局部；直接段／花括号作用域块中的取写块局部（含其中的若、循、试正文）；闭包共享捕获绑定，可更新捕获的块局部。:= 与取完全等价。参数属于本次调用局部。此提示不判断具体名称的运行时绑定。")

(defconst ru-lang--token-help
  '(("尽取" . "尽取：模块顶层全量导入。写作 尽取 外言 '如:数学'.，尽取须连写，不能替换成 :=。旧 尽 取 已停用并给出迁移提示；单字尽继续保留。保留原有静态解析、导出和名称冲突规则，长名称尽取值不拆分。此提示不检查此处语义。")
    ("尽" . "旧语法 尽 取 外言 已停用；请改用 尽取 外言 '文件.ru'.，尽取须连写。单字尽继续保留用于迁移诊断，没有兼容别名。")
    ("外言" . "外言：如竞用 外言 '如:竞'，如观用 外言 '如:观'。旧导入名如竞、如观、如:竞赛已移除，无兼容别名；产品名不变。如观需支持画布的如书宿主，普通 CLI 不显示画布。如:密是标准原生库；如见是随附三方 Win32 库。二者仅 Windows x64 本地 Python 显式 run --allow-native 可用，如书/C/Node/浏览器不可用。check --target python 只验证不执行。此提示不解析模块或执行源码。")
    ("典" . "典：键值映射。字面量 {目: 相, 目: 相}，表达式位置的空典 {}；语句位置的 {} 是作用域块。也可写 典: 目 对 相. 成。支持全角｛｝和尾逗号。")
    ("成" . "成：结束典字面量；外层语句的句点另写。")
    ("对" . "对：二元素对；在典字面量中分隔目与相。")
    ("事实" . "事实：真或假，与数不同。比较和非／且／或返回事实。为 事实 转换时仅空、假为假。")
    ("真" . "真：事实字面量。") ("假" . "假：事实字面量。")))

(defconst ru-lang--practical-member-help
  '(("缓存" . "如:观画布：缓存 宽 高 绘制，三个参数全必需，只在初始化调用。绘制是恰好接收一个临时目标的算／作，返回不可变图像，图像只读宽／高。透明独立默认状态，录制后目标失效；禁止嵌套、事件中创建及录制期间改主画布。最多 8 张、合计 4M 像素／128 KiB 定义、每张 2047 命令。不是图片加载、导出或可变画层。用户同名方法按其声明。")
    ("贴图" . "如:观画布：贴图 图像 横 纵，三个参数全必需，返回空；本画布有效图像按原尺寸绘制，受变换和裁剪影响，不重着色。透明度 source-over，放大为位图平滑缩放。每帧根命令加唯一引用配方合计 2048；关闭或新画布使旧图像失效。每帧仍传完整定义，不承诺60fps。用户同名方法按其声明。")
    ("贝塞尔" . "如:观画布：贝塞尔 起横 起纵 控一横 控一纵 控二横 控二纵 终横 终纵，八参全必需，支持全位置或全命名调用，返回空。单段三次曲线经过起终点，控制点不必经过；坐标为有限数且绝对值不超过 100000，拒绝事实与空。原生一次 moveTo 加 bezierCurveTo，只描边一次，不闭合、不填充，忽略且保留填色。坐标与矩阵、裁剪、透明描边、线宽深复制；重合或共线沿用原生退化行为，空描边或退化仍计入原有预算。不是二次贝塞尔或通用路径构造器。用户同名方法按其声明。")
    ("折线" . "如:观画布：折线 点阵，唯一参数必需，支持位置或点阵:调用，返回空。2～256 个二维阵点，坐标为有限数且绝对值不超过 100000，拒绝事实与空。开放路径只描边一次，不闭合、不填充，忽略且保留填色，半透明折点不逐段叠色。顶点与变换、裁剪、描边、线宽深复制；重复或全重合点合法，空描边或零长度仍计入原有预算。封闭填充用多边形。用户同名方法按其声明。")
    ("弧" . "如:观画布：弧 横 纵 宽 高 始角 转角，六个参数均必需，支持全位置或全命名，返回空。外接框同椭圆；始角与带符号转角为弧度，局部正向顺时针，负缩放镜像。只描边，忽略填色；零转角无像素但保留命令，绝对转角至少 2π 只画一整圈。有限数绝对值不超过 100000，宽高非负且可为零；非圆椭圆使用参数角。用户同名方法按其声明。")
    ("扇形" . "如:观画布：扇形 横 纵 宽 高 始角 转角，六个参数均必需，支持全位置或全命名，返回空。外接框同椭圆；始角与带符号转角为弧度，局部正向顺时针，负缩放镜像。填充并描边，部分扇形含两条半径边；零转角无像素但保留命令，绝对转角至少 2π 为无中心辐条的整椭圆。有限数绝对值不超过 100000，宽高非负且可为零；非圆椭圆使用参数角。用户同名方法按其声明。")
    ("经过秒" . "如:观画布：经过秒，零参数只读数值，创建时为 0；从创建画布起的宿主单调经过秒，包含暂停和隐藏页间隔。同次回调内冻结，反复读取不会推进；不是日期或墙钟。用户同名方法按其声明。")
    ("间隔秒" . "如:观画布：间隔秒，零参数只读数值。帧回调中是距上一实际帧开始的秒差；首帧及暂停恢复首帧为 0，输入回调为 0。隐藏间隔不截断，不补帧；物理积分可自行限制步长。同次回调内冻结，每帧仍只收帧序号。用户同名方法按其声明。")
    ("文字对齐" . "如:观画布：文字对齐 横向 纵向，两项句参数均必需；横向为左／中／右，纵向为上／中／下／基线，默认左上。设置跨回调保留并纳入保存／恢复；中部依据字体 em 方框，不是笔画包围盒或宽度测量。用户同名方法按其声明。")
    ("颜色" . "如:观：颜色 红 绿 蓝 不透明度，四个参数均为必需的 0～255 有限整数；支持全位置或全命名实参。返回小写 #rrggbbaa，0 全透明、255 不透明；不钳位、不舍入。用户同名方法按其声明。")
    ("逐位" . "内置阵：逐位 回调:二参算或作，按初始浅快照从0开始传入位、值；忽略返回值（含假/空），整体空。空阵也验证回调，完只结束当前作。用户同名方法按其声明。")
    ("逐目" . "内置典：逐目 回调:二参算或作，按初始无序浅条目快照传入目、相；忽略返回值，整体空。空典也验证回调。旧典列已移除，请改用逐目；目录列不变。用户同名方法按其声明。")
    ("排序" . "内置阵：排序，可选先于:二参算，返回新浅复制阵并稳定排序。默认全为有限数升序、句按Unicode码点、或同一形身份的单参算先于（可继承）；返回须为事实，无须同，不改比较运算符。显式先于覆盖默认规则；空/单项也返回新阵并验证参数。旧如:竞排序仍用三路数值比较器。用户同名方法按其声明。")
    ("另成" . "内置阵：另成 算法:一参算，先取浅快照，从左到右对每个元素调用一次，返回新阵；保留空，不筛选或展开，不接受作，空阵也验证算及参数个数。元素仍共享引用，欲复制对象须在算法中显式新。用户同名方法按其声明。")
    ("删" . "内置阵：删 位，原地删除合法位置并返回原元素；越界报错。用户同名方法按其声明。")
    ("弹" . "内置阵：弹，裸成员零参调用，移出最后项并返回原元素；空阵报错。用户同名方法按其声明。")
    ("增" . "内置阵：增 值:，追加元素。典：增 目: 相:，新增或覆盖条目。用户同名方法按其声明。")
    ("除" . "典：除 目:，删除条目，返回是否删除的事实。用户同名方法按其声明。")
    ("查" . "内置阵：查 值，按相等协议从初始浅快照返回首个位置，未找到为空。典：查 目:，按目返回相。用户同名方法按其声明。")))

(defun ru-lang--syntax-propertize (_start _end)
  "Apply string and comment syntax properties across the accessible buffer."
  (ru-lang--ensure-cache)
  (remove-text-properties (point-min) (point-max) '(syntax-table nil help-echo nil))
  (seq-doseq (token ru-lang--tokens)
    (let ((start (ru-lang--token-start token)) (end (ru-lang--token-end token)))
      (when (and (ru-lang--code-token-p token)
                 (member (ru-lang--token-text token) '("取" ":=")))
        (put-text-property start end 'help-echo ru-lang--assignment-help))
      (when (and (member (ru-lang--token-text token) '("段" "落"))
                 (eq (ru-lang--token-face token) 'font-lock-keyword-face))
        (put-text-property start end 'help-echo
                           "段: … 落.：独立词法作用域，与语句位置的 { … } 等价。每次进入创建新局部环境，落后必须有句点。"))
      (when (eq (ru-lang--token-kind token) 'name)
        (when-let ((help (cdr (assoc (ru-lang--token-text token) ru-lang--token-help))))
          (put-text-property start end 'help-echo help)))
      (when (eq (ru-lang--token-face token) 'font-lock-builtin-face)
        (when-let ((help (cdr (assoc (ru-lang--token-text token) ru-lang--practical-member-help))))
          (put-text-property start end 'help-echo help)))
      (pcase (ru-lang--token-kind token)
        ('comment
         (put-text-property start (1+ start) 'syntax-table (string-to-syntax "<"))
         (if (string-match-p "\\`解[.。]" (ru-lang--token-text token))
             (when (string-match-p "释[.。]\\'" (ru-lang--token-text token))
               (put-text-property (1- end) end 'syntax-table (string-to-syntax ">")))
           (when (< end (point-max))
             (put-text-property end (1+ end) 'syntax-table (string-to-syntax ">")))))
        ('string
         (put-text-property start (1+ start) 'syntax-table (string-to-syntax "|"))
         ;; An incomplete string has no closing fence.  Escaped final quotes
         ;; are not closers, even though they have the expected character.
         (let* ((open (char-after start))
                (close (or (cdr (assq open '((?‘ . ?’) (?“ . ?”)))) open))
                (pos (- end 2)) (slashes 0))
           (while (and (> pos start) (= (char-after pos) ?\\))
             (setq slashes (1+ slashes) pos (1- pos)))
           (when (and (> end (1+ start)) (= (char-before end) close)
                      (= (% slashes 2) 0))
             (put-text-property (1- end) end 'syntax-table (string-to-syntax "|")))))))))

(defun ru-lang--font-lock-match (limit)
  "Find the next cached token with a font-lock face before LIMIT."
  (ru-lang--ensure-cache)
  (let ((low 0) (high (length ru-lang--tokens)) found)
    ;; Binary search keeps incremental fontification cheap on large buffers.
    (while (< low high)
      (let ((mid (/ (+ low high) 2)))
        (if (< (ru-lang--token-start (aref ru-lang--tokens mid)) (point))
            (setq low (1+ mid))
          (setq high mid))))
    (while (and (< low (length ru-lang--tokens)) (not found)
                (< (ru-lang--token-start (aref ru-lang--tokens low)) limit))
      (let ((token (aref ru-lang--tokens low)))
        (when (ru-lang--token-face token)
          (set-match-data (list (ru-lang--token-start token) (ru-lang--token-end token)))
          (goto-char (ru-lang--token-end token))
          (setq found (ru-lang--token-face token))))
      (setq low (1+ low)))
    (setq ru-lang--font-lock-face found)))

(defun ru-lang-indent-line ()
  "Indent this line; preserve all lines within multiline string contents."
  (interactive)
  (ru-lang--ensure-cache)
  (let ((depth (cdr (assq (line-beginning-position) ru-lang--indents)))
        (offset (- (point) (save-excursion (back-to-indentation) (point)))))
    (when depth
      (indent-line-to (* ru-lang-indent-offset depth))
      (when (> offset 0) (forward-char offset)))))

(defun ru-lang-indent-region (start end)
  "Indent lines between START and END from bottom to top in one lexer pass."
  (ru-lang--ensure-cache)
  (let ((indents (reverse (copy-sequence ru-lang--indents))))
    (save-excursion
      (dolist (entry indents)
        (when (and (>= (car entry) start) (< (car entry) end) (cdr entry))
          (goto-char (car entry))
          (indent-line-to (* ru-lang-indent-offset (cdr entry))))))))

(defun ru-lang--navigation-blocks (definitions)
  "Return blocks, optionally restricted to DEFINITIONS."
  (ru-lang--ensure-cache)
  (if definitions
      (cl-remove-if-not #'ru-lang--definition-p ru-lang--blocks)
    ru-lang--blocks))

(defun ru-lang--backward (definitions)
  "Move to the previous opening, restricted to DEFINITIONS if non-nil."
  (let ((block (car (last (cl-remove-if-not
                          (lambda (b) (< (ru-lang--block-start b) (point)))
                          (ru-lang--navigation-blocks definitions))))))
    (if block (progn (goto-char (ru-lang--block-start block)) t)
      (goto-char (point-min)) nil)))

(defun ru-lang--forward (definitions)
  "Move past the innermost containing or next block or DEFINITIONS."
  (let* ((blocks (ru-lang--navigation-blocks definitions))
         (inside (cl-remove-if-not
                  (lambda (b) (and (<= (ru-lang--block-start b) (point))
                                   (> (ru-lang--block-end b) (point)))) blocks))
         (block (or (car (last inside))
                    (cl-find-if (lambda (b) (>= (ru-lang--block-start b) (point))) blocks))))
    (if block (progn (goto-char (ru-lang--block-end block)) t)
      (goto-char (point-max)) nil)))

(defun ru-lang-beginning-of-defun (&optional arg)
  "Move backward ARG definitions (forward when ARG is negative)."
  (let ((count (or arg 1)) (found t))
    (dotimes (_ (abs count))
      (setq found
            (if (< count 0)
                (let ((block (cl-find-if
                              (lambda (b) (> (ru-lang--block-start b) (point)))
                              (ru-lang--navigation-blocks t))))
                  (if block (progn (goto-char (ru-lang--block-start block)) t)
                    (goto-char (point-max)) nil))
              (ru-lang--backward t))))
    found))

(defun ru-lang-end-of-defun ()
  "Move past the current or next function, procedure or type definition."
  (ru-lang--forward t))

(defun ru-lang-backward-block (&optional arg)
  "Move backward ARG block openings; a negative ARG moves forward."
  (interactive "p")
  (dotimes (_ (abs (or arg 1)))
    (if (< (or arg 1) 0) (ru-lang--forward nil) (ru-lang--backward nil))))

(defun ru-lang-forward-block (&optional arg)
  "Move past ARG containing or following blocks; negative ARG goes backward."
  (interactive "p")
  (ru-lang-backward-block (- (or arg 1))))

(defun ru-lang-up-block ()
  "Move to the opening of the innermost enclosing language block."
  (interactive)
  (let ((block (car (last (cl-remove-if-not
                          (lambda (b) (and (< (ru-lang--block-start b) (point))
                                           (>= (ru-lang--block-end b) (point))))
                          (ru-lang--navigation-blocks nil))))))
    (when block (goto-char (ru-lang--block-start block)))))

(defun ru-lang--containing-structure ()
  "Return the innermost structure containing point, excluding its opening.
A completed structure excludes its end; an incomplete one includes EOF."
  (car (last (cl-remove-if-not
              (lambda (block)
                (and (< (ru-lang--block-start block) (point))
                     (or (< (point) (ru-lang--block-end block))
                         (and (not (ru-lang--block-closed block))
                              (= (point) (ru-lang--block-end block))))))
              ru-lang--structures))))

(defun ru-lang--move-structure (backward)
  "Move across one balanced structure at this level, BACKWARD if non-nil.
Do not cross the enclosing structure's boundary."
  (let* ((parent (ru-lang--containing-structure))
         (start (if parent (ru-lang--block-start parent) (1- (point-min))))
         (end (if parent (ru-lang--block-end parent) (1+ (point-max))))
         target)
    (dolist (block ru-lang--structures)
      (when (and (> (ru-lang--block-start block) start)
                 (< (ru-lang--block-start block) end)
                 (if backward
                     (and (ru-lang--block-closed block)
                          (<= (ru-lang--block-end block) (point)))
                   (>= (ru-lang--block-start block) (point))))
        (when (or (not target)
                  (if backward
                      (> (ru-lang--block-end block) (ru-lang--block-end target))
                    (< (ru-lang--block-start block) (ru-lang--block-start target))))
          ;; Ties retain the first (outermost) opening, so backward motion
          ;; always inverts a forward jump over a whole nested structure.
          (setq target block))))
    (unless target
      (user-error "No %s structure at this level" (if backward "previous" "next")))
    (unless (ru-lang--block-closed target)
      (user-error "Unclosed structure"))
    (goto-char (if backward (ru-lang--block-start target) (ru-lang--block-end target)))))

(defun ru-lang-forward-list (&optional arg)
  "Move across ARG balanced keyword blocks or bracket pairs at this level.
Negative ARG moves backward.  At a boundary or an incomplete target, report
an error without moving point; use `ru-lang-backward-up-list' to go outward."
  (interactive "p")
  (ru-lang--ensure-cache)
  (let ((count (or arg 1)))
    (goto-char
     (save-excursion
       (dotimes (_ (abs count)) (ru-lang--move-structure (< count 0)))
       (point)))))

(defun ru-lang-backward-list (&optional arg)
  "Move backward across ARG balanced structures; negative ARG moves forward."
  (interactive "p")
  (ru-lang-forward-list (- (or arg 1))))

(defun ru-lang-backward-up-list (&optional arg)
  "Move to ARG enclosing openings; negative ARG moves to enclosing ends.
This includes keyword blocks and bracket pairs, even unfinished openings.
On failure, leave point unchanged."
  (interactive "p")
  (ru-lang--ensure-cache)
  (let ((count (or arg 1)))
    (goto-char
     (save-excursion
       (dotimes (_ (abs count))
         (let ((parent (ru-lang--containing-structure)))
           (unless parent (user-error "No enclosing structure"))
           (when (and (< count 0) (not (ru-lang--block-closed parent)))
             (user-error "Unclosed structure"))
           (goto-char (if (< count 0) (ru-lang--block-end parent)
                        (ru-lang--block-start parent)))))
       (point)))))

(defun ru-lang-imenu-create-index ()
  "Build an Imenu index of types, methods and lexically nested definitions."
  (let (result)
    (dolist (block (ru-lang--navigation-blocks t) (nreverse result))
      (when (ru-lang--block-name block)
        (let ((parent block) names)
          (while parent
            (when (ru-lang--block-name parent)
              (push (ru-lang--block-name parent) names))
            (setq parent (ru-lang--block-parent parent)))
          (push (cons (concat (ru-lang--block-kind block) " "
                              (mapconcat #'identity names "@"))
                      (ru-lang--block-start block)) result))))))

(defvar ru-lang-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-r") #'ru-lang-run-file)
    (define-key map (kbd "C-c C-p") #'ru-lang-backward-block)
    (define-key map (kbd "C-c C-n") #'ru-lang-forward-block)
    (define-key map (kbd "C-c C-u") #'ru-lang-up-block)
    (define-key map (kbd "C-M-n") #'ru-lang-forward-list)
    (define-key map (kbd "C-M-p") #'ru-lang-backward-list)
    (define-key map (kbd "C-M-u") #'ru-lang-backward-up-list)
    map)
  "Keymap for `ru-lang-mode'.")

;;;###autoload
(define-derived-mode ru-lang-mode prog-mode "如"
  "Major mode for 如 (.ru) source files.
Use TAB and C-M-\\ for indentation; C-M-a/C-M-e for definitions;
C-M-n/C-M-p/C-M-u for balanced structures; C-c C-p/C-c C-n/C-c C-u
for legacy language-block movement; M-{/M-} for paragraphs.
C-c C-r runs the current file with `ru-lang-run-file'."
  :syntax-table ru-lang-mode-syntax-table
  ;; Ru positions count Unicode codepoints, not visual widths or UTF-16.
  (setq-local compilation-error-screen-columns nil)
  (setq-local compilation-first-column 1)
  (setq-local indent-tabs-mode nil)
  (setq-local indent-line-function #'ru-lang-indent-line)
  (setq-local indent-region-function #'ru-lang-indent-region)
  (setq-local syntax-propertize-function #'ru-lang--syntax-propertize)
  (setq-local syntax-propertize-extend-region-functions
              (list (lambda (start end)
                      (unless (and (= start (point-min)) (= end (point-max)))
                        (cons (point-min) (point-max))))))
  (setq-local font-lock-defaults '(((ru-lang--font-lock-match (0 ru-lang--font-lock-face)))))
  (setq-local beginning-of-defun-function #'ru-lang-beginning-of-defun)
  (setq-local end-of-defun-function #'ru-lang-end-of-defun)
  (setq-local imenu-create-index-function #'ru-lang-imenu-create-index)
  (setq-local comment-start "# ")
  (setq-local comment-end "")
  (setq-local comment-start-skip "\\(?:#\\|//\\|批[.。]\\)[ \t]*")
  (setq-local paragraph-start "[ \t]*$")
  (setq-local paragraph-separate "[ \t]*$")
  (setq-local parse-sexp-ignore-comments t))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.ru\\'" . ru-lang-mode))

(provide 'ru-lang-mode)
;;; ru-lang-mode.el ends here
