;;; ru-lang-mode.el --- Editing support for the 如 language -*- lexical-binding: t; -*-

;; Version: 0.1.0
;; Package-Requires: ((emacs "28.1"))
;; Keywords: languages
;; URL: https://github.com/uppet/ru-language

;;; Commentary:

;; A dependency-free major mode for ru-language 0.2.x source files.  The
;; lightweight lexer mirrors rulang/frontend.py; it deliberately accepts
;; incomplete input.  It is an editing aid, not a compiler or language server.
;; See README.md in this directory for loading, indentation and navigation.

;;; Code:

(require 'cl-lib)
(require 'imenu)
(require 'seq)

(defgroup ru-lang nil "Editing the 如 language." :group 'languages)

(defcustom ru-lang-indent-offset 4
  "Number of spaces for each 如 block or bracket nesting level."
  :type 'natnum :safe #'natnump :group 'ru-lang)

(defconst ru-lang--keywords
  '("显" "取" "为" "得" "破" "若" "则" "另" "然" "循" "次" "环"
    "算" "作" "法" "其" "且" "或" "非" "空" "对" "形" "象" "如" "新"
    "外言" "尽"))
(defconst ru-lang--types '("数" "句" "阵" "对" "空"))
(defconst ru-lang--builtins '("读" "含" "位" "段" "增" "量" "囫" "囵"))
(defconst ru-lang--pairs '(("算" . "法") ("作" . "为") ("形" . "象")
                            ("若" . "然") ("循" . "环")
                            ("(" . ")") ("[" . "]")))
(defconst ru-lang--punctuation
  '((?。 . ".") (?： . ":") (?（ . "(") (?） . ")")
    (?， . ",") (?［ . "[") (?］ . "]")))

(cl-defstruct (ru-lang--token (:constructor ru-lang--make-token))
  text start end kind face)
(cl-defstruct (ru-lang--block (:constructor ru-lang--make-block))
  kind start end name parent header)

(defvar-local ru-lang--font-lock-face nil)
(defvar-local ru-lang--cache-tick nil)
(defvar-local ru-lang--tokens nil)
(defvar-local ru-lang--blocks nil)
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
           ((or (= char ?#) (looking-at "//"))
            (end-of-line)
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

(defun ru-lang--analyze ()
  "Compute block pairs and desired line depths from `ru-lang--tokens'."
  (let ((tokens ru-lang--tokens) (stack nil) (blocks nil) (indents nil)
        (statement-start t) (line (point-min)) (index 0) previous
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
          ;; A string that began earlier owns this line, including its closing
          ;; delimiter.  Indenting it would alter the program's string value.
          (when (and (> index 0)
                     (eq (ru-lang--token-kind (aref tokens (1- index))) 'string)
                     (> (ru-lang--token-end (aref tokens (1- index))) line))
            (setq string-line t))
          (while (and (< index (length tokens))
                      (<= (ru-lang--token-start (aref tokens index)) end))
            (let* ((token (aref tokens index))
                   (text (ru-lang--token-text token))
                   (kind (ru-lang--token-kind token))
                   (next (aref next-tokens index))
                   (top (car stack))
                   (close (and top (cdr (assoc (ru-lang--block-kind top)
                                              ru-lang--pairs))))
                   (closer (and (ru-lang--code-token-p token)
                                (equal text close)
                                (or (not (equal text "为"))
                                    (and (not (ru-lang--block-header top))
                                         (or statement-start
                                             (and first
                                                  (not (and next
                                                            (member (ru-lang--token-text next)
                                                                    '("数" "句" "阵"))))))))))
                   (branch (and (ru-lang--code-token-p token) top
                                (equal (ru-lang--block-kind top) "若")
                                (member text '("则" "另")))))
              (unless (eq kind 'comment)
                (when first
                  (setq depth (max 0 (- (length stack)
                                        (if (or closer branch) 1 0))))
                  (setq first nil))
                (cond
                 ((eq kind 'string) (setq statement-start nil))
                 (closer
                  (setf (ru-lang--block-end top)
                        (if (and next (equal (ru-lang--token-text next) "."))
                            (ru-lang--token-end next)
                          (ru-lang--token-end token)))
                  (pop stack)
                  (setq statement-start t))
                 ((assoc text ru-lang--pairs)
                  (let* ((parent (cl-find-if #'ru-lang--definition-p stack))
                         (name (and (member text '("算" "作" "形")) next
                                    (eq (ru-lang--token-kind next) 'name)
                                    (not (member (ru-lang--token-text next) ru-lang--keywords))
                                    (ru-lang--token-text next)))
                         (block (ru-lang--make-block
                                 :kind text :start (ru-lang--token-start token)
                                 :end (point-max) :name name :parent parent
                                 :header (member text '("算" "作" "若")))))
                    (push block stack)
                    (unless (member text '("(" "[")) (push block blocks)))
                  (setq statement-start (equal text "循")))
                 ((or branch (and top (equal text ":")
                                  (member (ru-lang--block-kind top) '("算" "作" "形"))))
                  (setf (ru-lang--block-header top) nil)
                  (setq statement-start t))
                 ((or (equal text ".") (equal text "次"))
                  (setq statement-start t))
                 (t (setq statement-start nil)))
                ;; Set faces on complete lexical names, never keyword substrings.
                (when (eq kind 'name)
                  (setf (ru-lang--token-face token)
                        (cond
                         ((member previous '("算" "作")) 'font-lock-function-name-face)
                         ((or (member previous '("形" "如" "新"))
                              (and (equal previous "为") (not statement-start))
                              (member text ru-lang--types)) 'font-lock-type-face)
                         ((member text ru-lang--keywords) 'font-lock-keyword-face)
                         ((member text ru-lang--builtins) 'font-lock-builtin-face))))
                (setq previous (unless closer text))))
            (setq index (1+ index)))
          (push (cons line (unless string-line depth)) indents)
          (setq line (1+ end)))))
    (setq ru-lang--blocks (nreverse blocks)
          ru-lang--indents (nreverse indents))))

(defun ru-lang--ensure-cache ()
  "Refresh the lexical and structural cache after text or narrowing changes."
  (unless (and (equal ru-lang--cache-tick (buffer-chars-modified-tick))
               (equal ru-lang--cache-bounds (cons (point-min) (point-max))))
    (setq ru-lang--tokens (ru-lang--lex))
    (ru-lang--analyze)
    (setq ru-lang--cache-tick (buffer-chars-modified-tick)
          ru-lang--cache-bounds (cons (point-min) (point-max)))))

(defun ru-lang--syntax-propertize (_start _end)
  "Apply string and comment syntax properties across the accessible buffer."
  (ru-lang--ensure-cache)
  (remove-text-properties (point-min) (point-max) '(syntax-table nil))
  (seq-doseq (token ru-lang--tokens)
    (let ((start (ru-lang--token-start token)) (end (ru-lang--token-end token)))
      (pcase (ru-lang--token-kind token)
        ('comment
         (put-text-property start (1+ start) 'syntax-table (string-to-syntax "<"))
         (when (< end (point-max))
           (put-text-property end (1+ end) 'syntax-table (string-to-syntax ">"))))
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

(defun ru-lang-imenu-create-index ()
  "Build an Imenu index of types, functions, procedures and qualified methods."
  (let (result)
    (dolist (block (ru-lang--navigation-blocks t) (nreverse result))
      (when (ru-lang--block-name block)
        (let ((parent (ru-lang--block-parent block)))
          (push (cons (concat (ru-lang--block-kind block) " "
                              (when (and parent (ru-lang--block-name parent))
                                (concat (ru-lang--block-name parent) "@"))
                              (ru-lang--block-name block))
                      (ru-lang--block-start block)) result))))))

(defvar ru-lang-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-p") #'ru-lang-backward-block)
    (define-key map (kbd "C-c C-n") #'ru-lang-forward-block)
    (define-key map (kbd "C-c C-u") #'ru-lang-up-block)
    map)
  "Keymap for `ru-lang-mode'.")

;;;###autoload
(define-derived-mode ru-lang-mode prog-mode "如"
  "Major mode for 如 (.ru) source files.
Use TAB and C-M-\\ for indentation; C-M-a/C-M-e for definitions;
C-c C-p/C-c C-n/C-c C-u for language blocks; M-{/M-} for paragraphs."
  :syntax-table ru-lang-mode-syntax-table
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
  (setq-local comment-start-skip "\\(?:#\\|//\\)[ \t]*")
  (setq-local paragraph-start "[ \t]*$")
  (setq-local paragraph-separate "[ \t]*$")
  (setq-local parse-sexp-ignore-comments t))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.ru\\'" . ru-lang-mode))

(provide 'ru-lang-mode)
;;; ru-lang-mode.el ends here
