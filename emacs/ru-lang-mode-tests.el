;;; ru-lang-mode-tests.el --- Regression tests for 如 mode -*- lexical-binding: t; -*-

(require 'ert)
(require 'ru-lang-mode)

(defconst ru-lang-test--root
  (file-name-directory
   (directory-file-name (file-name-directory (or load-file-name buffer-file-name)))))

(defmacro ru-lang-test--buffer (source &rest body)
  "Evaluate BODY in a temporary 如 buffer containing SOURCE."
  (declare (indent 1))
  `(with-temp-buffer
     (insert ,source)
     (ru-lang-mode)
     (goto-char (point-min))
     ,@body))

(defun ru-lang-test--indent (source expected)
  "Check SOURCE indents to EXPECTED and remains stable on repeated indentation."
  (ru-lang-test--buffer source
    (indent-region (point-min) (point-max))
    (should (equal (buffer-string) expected))
    (indent-region (point-min) (point-max))
    (should (equal (buffer-string) expected))))

(ert-deftest ru-lang-auto-mode ()
  (with-temp-buffer
    (setq buffer-file-name "/tmp/example.ru")
    (set-auto-mode)
    (should (eq major-mode 'ru-lang-mode))))

(ert-deftest ru-lang-indent-functions-and-conversions ()
  (ru-lang-test--indent
   "算 平方 根 为 数：\n得 根 * 根.\n法\n作 展示 值 为 句:\n为乐 取 值 为 阵.\n显 值 为 句.\n为 .\n显 '完成'.\n"
   "算 平方 根 为 数：\n    得 根 * 根.\n法\n作 展示 值 为 句:\n    为乐 取 值 为 阵.\n    显 值 为 句.\n为 .\n显 '完成'.\n"))

(ert-deftest ru-lang-indent-object-methods ()
  (ru-lang-test--indent
   "形 人 如 动物:\n姓名 为 句.\n作 说 内容 为 句:\n显 内容.\n为\n算 名:\n得 其 姓名.\n法\n象\n"
   "形 人 如 动物:\n    姓名 为 句.\n    作 说 内容 为 句:\n        显 内容.\n    为\n    算 名:\n        得 其 姓名.\n    法\n象\n"))

(ert-deftest ru-lang-indent-branches-and-loops ()
  (ru-lang-test--indent
   "循 3 次\n若 1 则\n显 1.\n另\n循\n破.\n环\n然\n环\n"
   "循 3 次\n    若 1 则\n        显 1.\n    另\n        循\n            破.\n        环\n    然\n环\n"))

(ert-deftest ru-lang-indent-panic-and-rescue ()
  (ru-lang-test--indent
   "试\n卒 ‘失败’.\n救 原因\n显 原因.\n终.\n显 ‘继续’.\n"
   "试\n    卒 ‘失败’.\n救 原因\n    显 原因.\n终.\n显 ‘继续’.\n"))

(ert-deftest ru-lang-indent-nested-try-functions-and-branches ()
  (ru-lang-test--indent
   "作 主:\n试\n算 内:\n试\n卒 '内部'.\n救 内因\n得 内因.\n终.\n法\n循 2 次\n若 1 则\n卒 内.\n另\n破.\n然\n环\n救 原因\n试\n显 原因.\n救 另因\n卒 另因.\n终.\n为乐 取 1.\n终.\n为\n"
   "作 主:\n    试\n        算 内:\n            试\n                卒 '内部'.\n            救 内因\n                得 内因.\n            终.\n        法\n        循 2 次\n            若 1 则\n                卒 内.\n            另\n                破.\n            然\n        环\n    救 原因\n        试\n            显 原因.\n        救 另因\n            卒 另因.\n        终.\n        为乐 取 1.\n    终.\n为\n"))

(ert-deftest ru-lang-indent-compact-try-and-optional-colons ()
  (ru-lang-test--indent
   "试 卒 '失败'. 救 原因 显 原因. 终.\n试：\n卒 '失败'。\n救 原因：\n试: 救 内因: 终。\n终。\n显 1.\n"
   "试 卒 '失败'. 救 原因 显 原因. 终.\n试：\n    卒 '失败'。\n救 原因：\n    试: 救 内因: 终。\n终。\n显 1.\n"))

(ert-deftest ru-lang-indent-rescue-comments-and-quoted-words ()
  (ru-lang-test--indent
   "试 # 救 假 终\n卒 “救 原因 终 \\” 试”.\n// 救 假 终\n救 # 试 终\n原因 // 卒 ‘终’\n显 '试 救 终 卒'.\n终.\n"
   "试 # 救 假 终\n    卒 “救 原因 终 \\” 试”.\n    // 救 假 终\n救 # 试 终\n    原因 // 卒 ‘终’\n    显 '试 救 终 卒'.\n终.\n"))

(ert-deftest ru-lang-indent-rescue-multiline-strings ()
  (ru-lang-test--indent
   "试\n卒 ‘失败\n 救 伪名\n终’.\n救 原因\n显 原因.\n终.\n"
   "试\n    卒 ‘失败\n 救 伪名\n终’.\n救 原因\n    显 原因.\n终.\n"))

(ert-deftest ru-lang-indent-contextual-end-name-and-slice-argument ()
  (ru-lang-test--indent
   "算 段 始 为 数 终 为 数:\n试\n显 文 其 段 始:始\n终:终.\n显 函 名:终.\n显 文@段 (0) 终.\n显\n终.\n救 终\n显 终.\n终.\n得 终.\n法\n"
   "算 段 始 为 数 终 为 数:\n    试\n        显 文 其 段 始:始\n        终:终.\n        显 函 名:终.\n        显 文@段 (0) 终.\n        显\n        终.\n    救 终\n        显 终.\n    终.\n    得 终.\n法\n"))

(ert-deftest ru-lang-indent-io-types-and-identifiers ()
  (ru-lang-test--indent
   "作 试验 文件 为 件\n目录 为 录 结果 为 件作成果:\n救援 取 1.\n终点 取 2.\n卒业 取 3.\n显 显出 其 写 ‘试’.\n为\n"
   "作 试验 文件 为 件\n    目录 为 录 结果 为 件作成果:\n    救援 取 1.\n    终点 取 2.\n    卒业 取 3.\n    显 显出 其 写 ‘试’.\n为\n"))

(ert-deftest ru-lang-indent-multiline-condition ()
  (ru-lang-test--indent
   "若\n甲 == 乙\n则\n显 1.\n然\n"
   "若\n    甲 == 乙\n则\n    显 1.\n然\n"))

(ert-deftest ru-lang-indent-compact-blocks ()
  (ru-lang-test--indent
   "作 空事: 为.\n算 一: 得 1. 法.\n形 空形: 象.\n若 1 则 显 1. 另 显 2. 然.\n循 1 次 显 1. 环.\n显 2.\n"
   "作 空事: 为.\n算 一: 得 1. 法.\n形 空形: 象.\n若 1 则 显 1. 另 显 2. 然.\n循 1 次 显 1. 环.\n显 2.\n"))

(ert-deftest ru-lang-indent-brackets-and-fullwidth-punctuation ()
  (ru-lang-test--indent
   "算 和：\n数列 取 ［\n（1 +\n2），\n3\n］。\n得 数列［0］。\n法。\n"
   "算 和：\n    数列 取 ［\n        （1 +\n            2），\n        3\n    ］。\n    得 数列［0］。\n法。\n"))

(ert-deftest ru-lang-indent-comments-do-not-change-structure ()
  (ru-lang-test--indent
   "作 真正:\n# 为 算 若 法\n// 象 然 环\n显 '法'. # 为\n为\n"
   "作 真正:\n    # 为 算 若 法\n    // 象 然 环\n    显 '法'. # 为\n为\n"))

(ert-deftest ru-lang-indent-preserves-multiline-strings ()
  (ru-lang-test--indent
   "作 显示:\n显 “法\n  保持 缩进\n为” .\n显 '好了'.\n为\n"
   "作 显示:\n    显 “法\n  保持 缩进\n为” .\n    显 '好了'.\n为\n"))

(ert-deftest ru-lang-indent-multiline-conversion ()
  (ru-lang-test--indent
   "作 展示:\n值 取 '1'\n为 数.\n显 值.\n为\n"
   "作 展示:\n    值 取 '1'\n    为 数.\n    显 值.\n为\n"))

(ert-deftest ru-lang-indent-type-annotations-across-lines ()
  (ru-lang-test--indent
   "作 显示\n姓名 为 句\n年龄 为 数:\n显 姓名.\n为\n"
   "作 显示\n    姓名 为 句\n    年龄 为 数:\n    显 姓名.\n为\n"))

(ert-deftest ru-lang-indent-identifiers-containing-keywords ()
  (ru-lang-test--indent
   "作 算法:\n为乐 取 1.\n循环 取 为乐.\n显 自然而然.\n为\n"
   "作 算法:\n    为乐 取 1.\n    循环 取 为乐.\n    显 自然而然.\n为\n"))

(ert-deftest ru-lang-indent-offset-and-point ()
  (ru-lang-test--buffer "算 函:\n得 1.\n法\n"
    (setq-local ru-lang-indent-offset 2)
    (search-forward "得 ")
    (ru-lang-indent-line)
    (should (equal (buffer-string) "算 函:\n  得 1.\n法\n"))
    (should (eq (char-after) ?1))
    (beginning-of-line)
    (ru-lang-indent-line)
    (should (= (current-column) 2))))

(ert-deftest ru-lang-font-lock-whole-lexical-names ()
  (ru-lang-test--buffer "算 平方 根 为 数: 得 根. 法\n为乐 取 1. 算法 取 2. 显示 取 3. 读者 取 4.\n显 (读 '提示').\n"
    (font-lock-ensure)
    (dolist (entry '(("算 " . font-lock-keyword-face)
                     ("平方" . font-lock-function-name-face)
                     ("数:" . font-lock-type-face)
                     ("读 '" . font-lock-builtin-face)))
      (goto-char (point-min))
      (search-forward (car entry))
      (should (eq (get-text-property (- (point) (length (car entry))) 'face) (cdr entry))))
    (dolist (name '("为乐" "算法" "显示" "读者"))
      (goto-char (point-min))
      (search-forward name)
      (should-not (get-text-property (- (point) (length name)) 'face)))))

(ert-deftest ru-lang-font-lock-strings-and-comments ()
  (ru-lang-test--buffer "显 “算 '法' // 为” . # 若\n显 ‘形 \"象\" # 作’. // 环\n"
    (font-lock-ensure)
    (dolist (text '("算" "法" "为" "形" "象" "作"))
      (goto-char (point-min)) (search-forward text)
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-string-face)))
    (dolist (text '("若" "环"))
      (goto-char (point-min)) (search-forward text)
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-comment-face)))))

(ert-deftest ru-lang-font-lock-recovery-and-handler-binding ()
  (ru-lang-test--buffer "试\n卒 '失败'.\n救 # binding follows a comment\n原因\n显 原因.\n终.\n试 救 句 终.\n"
    (font-lock-ensure)
    (dolist (word '("试" "卒" "救" "终"))
      (goto-char (point-min)) (search-forward word)
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face)))
    (goto-char (point-min)) (search-forward "原因")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-variable-name-face))
    (search-forward "原因")
    (should-not (get-text-property (1- (point)) 'face))
    (search-forward "句")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-variable-name-face))))

(ert-deftest ru-lang-font-lock-contextual-end-name ()
  (ru-lang-test--buffer "算 终 终 为 数: 得 终. 法\n试\n显 文@段 始:0 终:2.\n救 终\n显 终.\n终.\n"
    (font-lock-ensure)
    (search-forward "终")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
    (dotimes (_ 3)
      (search-forward "终")
      (should-not (get-text-property (1- (point)) 'face)))
    (search-forward "终")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-variable-name-face))
    (search-forward "终")
    (should-not (get-text-property (1- (point)) 'face))
    (search-forward "终")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (should (equal (mapcar #'car (ru-lang-imenu-create-index)) '("算 终")))))

(ert-deftest ru-lang-font-lock-io-types-objects-and-member-names ()
  (ru-lang-test--buffer "作 主 文件 为 件 目录 为 录 结果 为 件作成果:\n读取@读.\n显出 其 写 '好'.\n错误@写 '错'.\n文件@在.\n文件@除.\n目录 其 # method follows a comment\n列.\n为\n"
    (font-lock-ensure)
    (dolist (word '("件" "录" "件作成果"))
      (goto-char (point-min)) (search-forward (concat "为 " word))
      (should (eq (get-text-property (- (point) (length word)) 'face) 'font-lock-type-face)))
    (dolist (word '("读取" "显出" "错误" "读." "写 '好'" "写 '错'" "在" "除" "列"))
      (goto-char (point-min)) (search-forward word)
      (should (eq (get-text-property (- (point) (length word)) 'face) 'font-lock-builtin-face)))))

(ert-deftest ru-lang-font-lock-io-methods-are-contextual-whole-names ()
  (ru-lang-test--buffer "写 取 1. 在 取 2. 除 取 3. 列 取 4.\n写信 取 5. 读取器 取 6. 显出值 取 7. 错误码 取 8. 件作成果值 取 9.\n试验 取 1. 救援 取 2. 终点 取 3. 卒业 取 4. 试² 取 5.\n算 写: 得 1. 法\n其 写信.\n"
    (font-lock-ensure)
    (dolist (word '("写" "在" "除" "列" "写信" "读取器" "显出值" "错误码" "件作成果值"
                    "试验" "救援" "终点" "卒业" "试²"))
      (goto-char (point-min)) (search-forward word)
      (should-not (get-text-property (- (point) (length word)) 'face)))
    (search-forward "算 写")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
    (search-forward "写信")
    (should-not (get-text-property (1- (point)) 'face))))

(ert-deftest ru-lang-font-lock-recovery-strings-and-comments ()
  (ru-lang-test--buffer "显 “试 救 终 卒 件 录 读取”. # 试 救 终\n显 ‘卒 \\’ 救’. // 卒\n"
    (font-lock-ensure)
    (dolist (word '("试" "救" "终" "卒" "件" "录" "读取"))
      (goto-char (point-min)) (search-forward word)
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-string-face)))
    (search-forward "# ")
    (dolist (word '("试" "救" "终"))
      (search-forward word)
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-comment-face)))
    (search-forward "// 卒")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-comment-face))))

(ert-deftest ru-lang-syntax-ascii-curly-and-escaped-quotes ()
  (dolist (source '("\"a'形\\\"b\"" "'a\"形\\'b'" "“a‘形\\”b”" "‘a“形\\’b’"))
    (ru-lang-test--buffer source
      (syntax-propertize (point-max))
      (search-forward "形")
      (should (nth 3 (syntax-ppss (1- (point)))))
      (should-not (nth 3 (syntax-ppss (point-max)))))))

(ert-deftest ru-lang-syntax-unclosed-escaped-quote ()
  (ru-lang-test--buffer "显 ‘abc\\’"
    (syntax-propertize (point-max))
    (should (nth 3 (syntax-ppss (point-max))))))

(ert-deftest ru-lang-syntax-repairs-after-edit ()
  (ru-lang-test--buffer "显 “字\n法”.\n显 1.\n"
    (font-lock-ensure)
    (search-forward "”")
    (delete-char -1)
    (font-lock-ensure)
    (goto-char (point-max))
    (should (nth 3 (syntax-ppss)))
    (goto-char (point-min)) (search-forward "法") (insert "”")
    (font-lock-ensure)
    (should-not (nth 3 (syntax-ppss (point-max))))))

(ert-deftest ru-lang-syntax-bracket-motion ()
  (dolist (text '("(1 + 2)" "［1，2］" "（1 + 2）" "[1, 2]"))
    (ru-lang-test--buffer text
      (forward-sexp)
      (should (= (point) (point-max)))
      (backward-sexp)
      (should (= (point) (point-min))))))

(ert-deftest ru-lang-imenu-includes-qualified-methods ()
  (ru-lang-test--buffer "形 人:\n姓名 为 句.\n作 说: 显 其 姓名. 为\n算 名: 得 其 姓名. 法\n象\n算 元初: 得 0. 法\n# 算 假: 法\n显 '作 也是假的: 为'.\n"
    (should (equal (mapcar #'car (ru-lang-imenu-create-index))
                   '("形 人" "作 人@说" "算 人@名" "算 元初")))))

(ert-deftest ru-lang-definition-navigation ()
  (ru-lang-test--buffer "形 人:\n算 名:\n得 '甲'.\n法\n象\n算 元初: 得 0. 法\n"
    (search-forward "得 '甲'")
    (beginning-of-defun)
    (should (looking-at "算 名"))
    (end-of-defun)
    ;; The standard command also advances over the closing line newline.
    (should (looking-at "象"))
    (beginning-of-defun)
    (should (looking-at "算 名"))
    (ru-lang-beginning-of-defun 1)
    (should (looking-at "形 人"))))

(ert-deftest ru-lang-block-navigation ()
  (ru-lang-test--buffer "作 主:\n循\n若 1 则\n显 1.\n然\n破.\n环\n为\n"
    (search-forward "显 1")
    (ru-lang-up-block)
    (should (looking-at "若"))
    (ru-lang-forward-block)
    (should (eq (char-before) ?然))
    (ru-lang-forward-block)
    (should (eq (char-before) ?环))
    (ru-lang-forward-block)
    (should (eq (char-before) ?为))
    (goto-char (point-max))
    (ru-lang-backward-block 2)
    (should (looking-at "循"))))

(ert-deftest ru-lang-balanced-structure-round-trips ()
  (dolist (source '("算 外: 若 1 则 显 (1). 然. 法."
                    "作 外: 循 2 次 显 ［1，2］. 环. 为."
                    "形 外: 算 内: 得 1. 法 象."
                    "试 试 卒 '坏'. 救 内因 显 内因. 终. 救 因 显 因. 终."
                    "若 1 则 显 (1). 另 显 [2]. 然."
                    "循 2 次 显 1. 环."))
    (ru-lang-test--buffer source
      (call-interactively (key-binding (kbd "C-M-n")))
      (should (= (point) (point-max)))
      (call-interactively (key-binding (kbd "C-M-p")))
      (should (= (point) (point-min))))))

(ert-deftest ru-lang-balanced-structure-nesting-and-boundaries ()
  (ru-lang-test--buffer "算 外:\n若 1 则\n循 2 次\n显 （[1，2]）.\n环.\n然.\n法."
    (search-forward "若")
    (backward-char)
    (let ((branch (point)))
      (ru-lang-forward-list)
      (should (looking-at "\n法"))
      (ru-lang-backward-list)
      (should (= (point) branch))
      (ru-lang-backward-up-list)
      (should (looking-at "算 外")))
    (search-forward "循")
    (backward-char)
    (ru-lang-forward-list)
    ;; Just after a closer belongs to the parent, not the finished child.
    (ru-lang-backward-up-list)
    (should (looking-at "若"))
    (search-forward "环")
    (backward-char)
    (ru-lang-backward-up-list)
    (should (looking-at "循"))
    (goto-char (point-max))
    (should-error (ru-lang-backward-up-list) :type 'user-error)
    (should (= (point) (point-max)))))

(ert-deftest ru-lang-balanced-brackets-and-terminators ()
  (dolist (source '("([1, 2])." "（［1，2］）。" "(［1，2］)." "［（1），2］."))
    (ru-lang-test--buffer source
      (ru-lang-forward-list)
      ;; Statement punctuation belongs to keyword blocks, not bracket pairs.
      (should (= (point) (1- (point-max))))
      (ru-lang-backward-list)
      (should (= (point) (point-min)))
      (forward-char)
      (let ((child (point)))
        (ru-lang-forward-list)
        (ru-lang-backward-list)
        (should (= (point) child)))
      (ru-lang-backward-up-list)
      (should (= (point) (point-min))))))

(ert-deftest ru-lang-balanced-structure-prefix-arguments ()
  (ru-lang-test--buffer "作 外:\n若 1 则 显 1. 然.\n试 显 2. 救 因 显 因. 终.\n为."
    (search-forward "若")
    (backward-char)
    (let ((first (point)))
      (ru-lang-forward-list 2)
      (should (looking-at "\n为"))
      (ru-lang-backward-list 2)
      (should (= (point) first))
      (ru-lang-backward-list -2)
      (ru-lang-forward-list -2)
      (should (= (point) first))
      (ru-lang-forward-list 0)
      (ru-lang-backward-list 0)
      (ru-lang-backward-up-list 0)
      (should (= (point) first)))
    (search-forward "显 1")
    (let ((inside (point)))
      (ru-lang-backward-up-list -2)
      (should (= (point) (point-max)))
      (goto-char inside)
      (ru-lang-backward-up-list 2)
      (should (= (point) (point-min))))))

(ert-deftest ru-lang-balanced-structure-errors-preserve-point ()
  (ru-lang-test--buffer "(0)\n算 外:\n显 1.\n若 1 则 显 2. 然.\n显 3.\n法.\n(4)"
    (search-forward "显 1")
    (let ((before-child (point)))
      (should-error (ru-lang-backward-list) :type 'user-error)
      (should (= (point) before-child))
      ;; Counts cannot leave a partially completed jump on failure.
      (should-error (ru-lang-forward-list 2) :type 'user-error)
      (should (= (point) before-child)))
    (search-forward "显 3")
    (let ((after-child (point)))
      (should-error (ru-lang-forward-list) :type 'user-error)
      (should (= (point) after-child)))
    (goto-char (point-min))
    (should-error (ru-lang-backward-list) :type 'user-error)
    (should-error (ru-lang-backward-up-list) :type 'user-error)
    (should (= (point) (point-min)))
    (goto-char (point-max))
    (should-error (ru-lang-forward-list) :type 'user-error)
    (should (= (point) (point-max)))))

(ert-deftest ru-lang-balanced-structure-ignores-strings-and-comments ()
  (ru-lang-test--buffer "# 若 1 则 ( 假 然\n显 ‘试 ［ 然’.\n// 算 假: 法\n显 \"(作 为)\".\n(1)\n显 '法 ]'.\n试 显 '终'. 救 因 显 因. 终."
    (ru-lang-forward-list)
    (should (looking-at "\n显 '法"))
    (ru-lang-backward-list)
    (should (looking-at "(1)"))
    (ru-lang-forward-list 2)
    (should (= (point) (point-max)))
    (ru-lang-backward-list)
    (should (looking-at "试 显"))))

(ert-deftest ru-lang-balanced-structure-incomplete-and-empty ()
  (dolist (source '("" "算 外:" "若 (\n［" "试\n试\n卒 '未闭合"))
    (ru-lang-test--buffer source
      (should-error (ru-lang-forward-list) :type 'user-error)
      (should (= (point) (point-min)))
      (goto-char (point-max))
      (let ((end (point)))
        (should-error (ru-lang-backward-list) :type 'user-error)
        (should (= (point) end))
        (should-error (ru-lang-backward-up-list -1) :type 'user-error)
        (should (= (point) end)))
      (unless (equal source "")
        (ru-lang-backward-up-list)
        (should (< (point) (point-max)))))))

(ert-deftest ru-lang-balanced-structure-cache-and-narrowing ()
  (ru-lang-test--buffer "作 外:\n(1)\n为."
    (search-forward "(1)")
    (narrow-to-region (- (point) 3) (point))
    (goto-char (point-min))
    (ru-lang-forward-list)
    (ru-lang-backward-list)
    (should (= (point) (point-min)))
    (should-error (ru-lang-backward-up-list) :type 'user-error)
    (widen)
    (ru-lang-backward-up-list)
    (should (looking-at "作 外"))
    (goto-char (point-max))
    (insert "\n[2]")
    (ru-lang-backward-list)
    (should (looking-at "\\[2\\]"))
    (delete-region (point) (point-max))
    (ru-lang-backward-list)
    (should (looking-at "作 外"))))

(ert-deftest ru-lang-try-block-navigation ()
  (ru-lang-test--buffer "作 主:\n试\n试\n卒 '内部'.\n救 内因\n显 内因.\n终.\n救 原因\n显 原因.\n终.\n为\n"
    (search-forward "卒 '内部'")
    (ru-lang-up-block)
    (should (looking-at "试\n卒"))
    (ru-lang-forward-block)
    (should (looking-at "\n救 原因"))
    (ru-lang-forward-block)
    (should (looking-at "\n为"))
    (ru-lang-forward-block)
    (should (eq (char-before) ?为))
    (ru-lang-backward-block)
    (should (looking-at "试\n卒"))
    (ru-lang-up-block)
    (should (looking-at "试\n试"))
    (ru-lang-up-block)
    (should (looking-at "作 主"))))

(ert-deftest ru-lang-try-definition-navigation-and-imenu ()
  (ru-lang-test--buffer "算 主:\n试\n算 内:\n试 卒 '坏'. 救 因 得 1. 终.\n法\n救 因\n得 0.\n终.\n法\n算 后: 得 2. 法\n"
    (should (equal (mapcar #'car (ru-lang-imenu-create-index))
                   '("算 主" "算 主@内" "算 后")))
    (search-forward "卒 '坏'")
    (ru-lang-beginning-of-defun)
    (should (looking-at "算 内"))
    (ru-lang-end-of-defun)
    (should (looking-at "\n救 因"))
    (ru-lang-end-of-defun)
    (should (looking-at "\n算 后"))))

(ert-deftest ru-lang-navigation-empty-and-incomplete ()
  (dolist (source '("" "算" "作 主:\n显 ‘未闭合\n然" "若 (\n［" "法 然 环 为 象" "形 人: 作 说:"
                    "试" "试 卒" "试 卒 '未闭合" "试 救" "试 救 # 名称未写"
                    "试 救 原因" "试 试 救 内因" "试 算 未完:" "救 原因 终."))
    (ru-lang-test--buffer source
      (font-lock-ensure)
      (indent-region (point-min) (point-max))
      (ru-lang-forward-block 5)
      (ru-lang-backward-block 5)
      (ru-lang-up-block)
      (ru-lang-beginning-of-defun -2)
      (ru-lang-end-of-defun)
      (ru-lang-imenu-create-index)
      (should (<= (point-min) (point) (point-max))))))

(ert-deftest ru-lang-comment-dwim-and-uncomment ()
  (ru-lang-test--buffer "显 1.\n显 2.\n"
    (comment-region (point-min) (point-max))
    (should (equal (buffer-string) "# 显 1.\n# 显 2.\n"))
    (uncomment-region (point-min) (point-max))
    (should (equal (buffer-string) "显 1.\n显 2.\n"))))

(ert-deftest ru-lang-paragraph-navigation ()
  (ru-lang-test--buffer "显 1.\n显 2.\n\n显 3.\n"
    (forward-paragraph)
    (should (= (line-number-at-pos) 3))
    (forward-paragraph)
    (should (= (point) (point-max)))
    (backward-paragraph)
    (should (<= (line-number-at-pos) 4))))

(ert-deftest ru-lang-mode-hooks-and-keymap ()
  (ru-lang-test--buffer ""
    (should (eq (key-binding (kbd "C-c C-p")) #'ru-lang-backward-block))
    (should (eq (key-binding (kbd "C-c C-n")) #'ru-lang-forward-block))
    (should (eq (key-binding (kbd "C-c C-u")) #'ru-lang-up-block))
    (should (eq (key-binding (kbd "C-M-n")) #'ru-lang-forward-list))
    (should (eq (key-binding (kbd "C-M-p")) #'ru-lang-backward-list))
    (should (eq (key-binding (kbd "C-M-u")) #'ru-lang-backward-up-list))
    (should-not indent-tabs-mode)))

(ert-deftest ru-lang-cache-invalidates-on-text-and-narrowing ()
  (ru-lang-test--buffer "算 甲: 得 1. 法\n算 乙: 得 2. 法\n"
    (should (= (length (ru-lang-imenu-create-index)) 2))
    (goto-char (point-max)) (insert "算 丙: 得 3. 法\n")
    (should (= (length (ru-lang-imenu-create-index)) 3))
    (goto-char (point-min)) (forward-line)
    (narrow-to-region (point-min) (point))
    (should (= (length (ru-lang-imenu-create-index)) 1))
    (widen)
    (should (= (length (ru-lang-imenu-create-index)) 3))))

(ert-deftest ru-lang-comments-between-tokens ()
  (ru-lang-test--indent
   "作 f:\n显 1\n为 # comment\n句.\n为.\n显 2.\n"
   "作 f:\n    显 1\n    为 # comment\n    句.\n为.\n显 2.\n")
  (ru-lang-test--buffer "算 # comment\nf:\n得 1.\n法.\n"
    (should (equal (mapcar #'car (ru-lang-imenu-create-index)) '("算 f")))))

(ert-deftest ru-lang-forward-definition-start ()
  (ru-lang-test--buffer "算 一: 得 1. 法\n算 二: 得 2. 法\n"
    (beginning-of-defun -1)
    (should (looking-at "算 二"))
    (beginning-of-defun -1)
    (should (= (point) (point-max)))))

(ert-deftest ru-lang-unicode-numeric-name-parts ()
  (ru-lang-test--buffer "若² 取 1.\n显 若².\n作½ 取 1.\n显 作½.\n"
    (font-lock-ensure)
    (should-not (ru-lang--navigation-blocks nil))
    (should-not (get-text-property (point-min) 'face))
    (let ((source (buffer-string)))
      (indent-region (point-min) (point-max))
      (should (equal source (buffer-string))))))

(ert-deftest ru-lang-all-editing-prefixes ()
  (let ((source "形 人:\n作 说 姓名 为 句:\n循 2 次\n若 1 则\n显 [‘法’, \"为\"].\n另\n显 ‘好’.\n然\n环\n为\n象\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (ru-lang-forward-block 3)
        (ru-lang-backward-block 3)
        (ru-lang-up-block)
        (ru-lang-imenu-create-index)))))

(ert-deftest ru-lang-recovery-all-editing-prefixes ()
  (let ((source "作 主 文件 为 件:\n试\n算 内 终 为 数:\n试：\n卒 ‘救 \\’ 终’.\n救 # 试 终\n原因：\n显 终.\n终.\n法\n救 原因\n试 显 文件@读. 救 内因 显 内因. 终.\n错误 其 写 原因.\n终.\n为\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-forward-block 5)
        (ru-lang-backward-block 5)
        (ru-lang-up-block)
        (ru-lang-beginning-of-defun)
        (ru-lang-end-of-defun)
        (ru-lang-imenu-create-index)))))

(ert-deftest ru-lang-repository-examples-preserve-tokens ()
  (dolist (file (directory-files-recursively
                (expand-file-name "examples" ru-lang-test--root) "\\.ru\\'"))
    (with-temp-buffer
      (insert-file-contents file)
      (ru-lang-mode)
      (font-lock-ensure)
      (let ((original (mapcar (lambda (token)
                                (cons (ru-lang--token-kind token)
                                      (ru-lang--token-text token)))
                              (ru-lang--lex))))
        (indent-region (point-min) (point-max))
        (should (equal original
                       (mapcar (lambda (token)
                                 (cons (ru-lang--token-kind token)
                                       (ru-lang--token-text token)))
                               (ru-lang--lex))))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))))))

(ert-deftest ru-lang-mark-definition ()
  (ru-lang-test--buffer "算 一:\n得 1.\n法\n\n算 二: 得 2. 法\n"
    (search-forward "得 1")
    (mark-defun)
    (should (looking-at "算 一"))
    (should (equal (buffer-substring-no-properties (point) (mark))
                   "算 一:\n得 1.\n法\n"))))

(ert-deftest ru-lang-closure-nested-definitions-and-references-indent ()
  (ru-lang-test--indent
   "算 工厂 初值 为 数:\n数值 取 初值.\n算 增 步 为 数:\n数值 取 数值+步.\n得 数值.\n法\n回调 取 算 增.\n得 回调.\n法\n回调 取 工厂 1.\n显 (回调 2).\n"
   "算 工厂 初值 为 数:\n    数值 取 初值.\n    算 增 步 为 数:\n        数值 取 数值+步.\n        得 数值.\n    法\n    回调 取 算 增.\n    得 回调.\n法\n回调 取 工厂 1.\n显 (回调 2).\n"))

(ert-deftest ru-lang-closure-types-do-not-open-blocks ()
  (ru-lang-test--indent
   "形 操作集:\n生成 为 算.\n输出 为 作.\n作 执行 回调 为 作\n工厂 为 算:\n回调().\n显 工厂().\n为\n象\n算 应用 回调 为 算 值 为 数:\n得 回调 值.\n法\n"
   "形 操作集:\n    生成 为 算.\n    输出 为 作.\n    作 执行 回调 为 作\n        工厂 为 算:\n        回调().\n        显 工厂().\n    为\n象\n算 应用 回调 为 算 值 为 数:\n    得 回调 值.\n法\n"))

(ert-deftest ru-lang-closure-reference-statements-are-not-definitions ()
  (ru-lang-test--buffer "算 平方.\n作 输出.\n算 模块 其 平方.\n作 对象@输出.\n算 (取得对象 1) 其 方法.\n算 列[0].\n显 [(算 平方),作 输出].\n"
    (font-lock-ensure)
    (should-not (ru-lang--navigation-blocks t))
    (should-not (ru-lang-imenu-create-index))
    (let ((original (buffer-string)))
      (indent-region (point-min) (point-max))
      (should (equal original (buffer-string))))))

(ert-deftest ru-lang-closure-type-and-reference-faces ()
  (ru-lang-test--buffer "算 应用 回调 为 算 次数 为 数:\n本地 取 算 应用.\n得 回调.\n法\n作 执行 回调 为 作:\n回调().\n为\n"
    (font-lock-ensure)
    (search-forward "算")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (search-forward "应用")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
    (search-forward "为 算")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (search-forward "次数")
    (should-not (get-text-property (1- (point)) 'face))
    (search-forward "取 算")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (search-forward "应用")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
    (search-forward "为 作")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))))

(ert-deftest ru-lang-closure-imenu-complete-lexical-paths ()
  (ru-lang-test--buffer "形 工厂:\n算 创建:\n算 中层:\n作 内层: 显 1. 为\n得 作 内层.\n法\n得 算 中层.\n法\n象\n引用 取 算 工厂.\n"
    (should (equal (mapcar #'car (ru-lang-imenu-create-index))
                   '("形 工厂" "算 工厂@创建" "算 工厂@创建@中层" "作 工厂@创建@中层@内层")))))

(ert-deftest ru-lang-closure-navigation-skips-references-and-types ()
  (ru-lang-test--buffer "算 外 回调 为 算:\n算 内:\n得 回调().\n法\n另值 取 算 内.\n得 另值.\n法\n"
    (search-forward "得 回调")
    (ru-lang-beginning-of-defun)
    (should (looking-at "算 内"))
    (ru-lang-forward-list)
    (should (looking-at "\n另值"))
    (ru-lang-backward-list)
    (should (looking-at "算 内"))
    (ru-lang-backward-up-list)
    (should (looking-at "算 外"))
    (ru-lang-forward-list)
    (should (= (point) (1- (point-max))))
    (ru-lang-backward-list)
    (should (= (point) (point-min)))))

(ert-deftest ru-lang-closure-rescue-definition-and-reference-comments ()
  (ru-lang-test--indent
   "试\n卒 '坏'.\n救 原因\n算 # 声明\n保存:\n得 原因.\n法\n副本 取 算 # 引用\n保存.\n显 副本().\n终.\n"
   "试\n    卒 '坏'.\n救 原因\n    算 # 声明\n        保存:\n        得 原因.\n    法\n    副本 取 算 # 引用\n    保存.\n    显 副本().\n终.\n"))

(ert-deftest ru-lang-closure-all-editing-prefixes ()
  (let ((source "算 工厂 参数 为 算:\n算 内:\n得 参数().\n法\n副本 取 算 内.\n得 [副本,算 内].\n法\n算 工厂.\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-imenu-create-index)
        (ru-lang-beginning-of-defun)
        (ru-lang-end-of-defun)))))

(ert-deftest ru-lang-contest-stream-members-and-bridge-faces ()
  (ru-lang-test--buffer "尽 取 外言 '如:竞'.\n入 取 读入.\n出 取 蓄出.\n显 入 其 词.\n显 入@数.\n显 入 其 # 成员之前的注释\n行.\n出 其 写 内容:'甲'.\n出@行 值:42.\n出 其 清.\n显 __如竞.\n"
    (font-lock-ensure)
    (dolist (text '("词." "数." "行." "写 内容" "行 值" "清." "__如竞"))
      (goto-char (point-min)) (search-forward text)
      (should (eq (get-text-property (- (point) (length text)) 'face)
                  'font-lock-builtin-face)))
    (should-not (ru-lang-imenu-create-index))))

(ert-deftest ru-lang-contest-library-names-remain-ordinary ()
  (let ((names '("读入" "扫句" "拆词" "拆行" "字列" "合句" "排序"
                 "取整" "小" "大" "绝对" "整除" "蓄出" "词" "行" "清"
                 "读入器" "排序表" "__如竞者" "竞赛" "如竞" "__竞赛")))
    (ru-lang-test--buffer (mapconcat (lambda (name) (concat name " 取 1.")) names "\n")
      (font-lock-ensure)
      (dolist (name names)
        (goto-char (point-min)) (search-forward name)
        (should-not (get-text-property (- (point) (length name)) 'face))))
    (ru-lang-test--buffer "算 排序 列 为 阵 比较 为 算:\n得 列.\n法\n算 读入: 得 1. 法\n引用 取 算 读入.\n"
      (font-lock-ensure)
      (should (equal (mapcar #'car (ru-lang-imenu-create-index))
                     '("算 排序" "算 读入")))
      (search-forward "排序")
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
      (search-forward "为 算")
      (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face)))))

(ert-deftest ru-lang-contest-qualified-references-and-indent ()
  (ru-lang-test--indent
   "竞 取 外言 '如:竞'.\n算 造比较 方向 为 数:\n算 比较 左 为 数 右 为 数:\n得 (左-右)*方向.\n法\n得 算 比较.\n法\n排 取 算 竞 其 排序.\n入 取 竞 其 读入.\n出 取 竞 其 蓄出.\n循\n值 取 入 其 数.\n若 值 == 空 则 破. 然\n出 其 行 值.\n环\n出 其 清.\n"
   "竞 取 外言 '如:竞'.\n算 造比较 方向 为 数:\n    算 比较 左 为 数 右 为 数:\n        得 (左-右)*方向.\n    法\n    得 算 比较.\n法\n排 取 算 竞 其 排序.\n入 取 竞 其 读入.\n出 取 竞 其 蓄出.\n循\n    值 取 入 其 数.\n    若 值 == 空 则 破. 然\n    出 其 行 值.\n环\n出 其 清.\n"))

(ert-deftest ru-lang-contest-all-editing-prefixes ()
  (let ((source "尽 取 外言 '如:竞'.\n算 工厂 方向 为 数:\n算 比较 左 为 数 右 为 数: 得 (左-右)*方向. 法\n得 算 比较.\n法\n入 取 读入.\n出 取 蓄出.\n循\n词值 取 入 其 词.\n若 词值 == 空 则 破. 然\n出 其 行 词值.\n环\n出 其 清.\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-imenu-create-index)
        (ru-lang-forward-block 3)
        (ru-lang-backward-block 3)
        (ru-lang-up-block)))))

(ert-deftest ru-lang-anonymous-typed-and-zero-parameter-indent ()
  (ru-lang-test--indent
   "平方 取 算 值 为 数:\n得 值 * 值.\n法.\n问候 取 作 名 为 句:\n显 ('你好，' + 名).\n为.\n报到 取 作:\n显 '到了'.\n为.\n报到().\n"
   "平方 取 算 值 为 数:\n    得 值 * 值.\n法.\n问候 取 作 名 为 句:\n    显 ('你好，' + 名).\n为.\n报到 取 作:\n    显 '到了'.\n为.\n报到().\n"))

(ert-deftest ru-lang-anonymous-return-nested-and-control-flow-indent ()
  (ru-lang-test--indent
   "算 工厂 初值 为 数:\n当前 取 初值.\n得 算 步 为 数:\n若 步 则\n当前 取 当前 + 步.\n然\n得 算:\n得 当前.\n法.\n法.\n法\n若 1 则\n回调 取 作:\n循 2 次\n显 '到了'.\n环\n为.\n然\n"
   "算 工厂 初值 为 数:\n    当前 取 初值.\n    得 算 步 为 数:\n        若 步 则\n            当前 取 当前 + 步.\n        然\n        得 算:\n            得 当前.\n        法.\n    法.\n法\n若 1 则\n    回调 取 作:\n        循 2 次\n            显 '到了'.\n        环\n    为.\n然\n"))

(ert-deftest ru-lang-anonymous-containers-and-arguments-indent ()
  (ru-lang-test--indent
   "操作们 取 [\n算 值 为 数:\n得 值 + 1.\n法,\n作:\n显 '完成'.\n为\n].\n显 (应用 (算 值 为 数:\n得 值 * 值.\n法) 5).\n"
   "操作们 取 [\n    算 值 为 数:\n        得 值 + 1.\n    法,\n    作:\n        显 '完成'.\n    为\n].\n显 (应用 (算 值 为 数:\n            得 值 * 值.\n        法) 5).\n"))

(ert-deftest ru-lang-anonymous-faces-do-not-name-first-parameter ()
  (ru-lang-test--buffer "回调 取 算 值 为 数 操作 为 作:\n得 值.\n法.\n输出 取 作 名 为 句: 显 名. 为.\n引用 取 算 已有.\n"
    (font-lock-ensure)
    (search-forward "取 算")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (search-forward "值")
    (should-not (get-text-property (1- (point)) 'face))
    (search-forward "为 数")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (search-forward "为 作")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (search-forward "取 作")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (search-forward "名")
    (should-not (get-text-property (1- (point)) 'face))
    (search-forward "已有")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))))

(ert-deftest ru-lang-anonymous-imenu-keeps-only-named-definitions ()
  (ru-lang-test--buffer "算 工厂:\n得 算 值 为 数:\n作 输出: 显 值. 为\n得 作 输出.\n法.\n法\n报到 取 作: 显 '到了'. 为.\n"
    (should (equal (mapcar #'car (ru-lang-imenu-create-index))
                   '("算 工厂" "作 工厂@输出")))
    (let ((blocks (ru-lang--navigation-blocks t)))
      (should (= (length blocks) 4))
      (should (ru-lang--block-literal (nth 1 blocks)))
      (should-not (ru-lang--block-name (nth 1 blocks)))
      (should (ru-lang--block-literal (nth 3 blocks))))))

(ert-deftest ru-lang-anonymous-navigation-does-not-consume-outer-dot ()
  (ru-lang-test--buffer "回调 取 算 值 为 数: 得 值. 法.\n报到 取 作: 显 '到了'. 为。\n"
    (search-forward "取 ")
    (let ((start (point)))
      (ru-lang-forward-list)
      (should (looking-at "\\.\n报到"))
      (ru-lang-backward-list)
      (should (= (point) start))
      (search-forward "得 值")
      (ru-lang-beginning-of-defun)
      (should (= (point) start))
      (ru-lang-end-of-defun)
      (should (looking-at "\\.\n报到")))
    (search-forward "取 ")
    (let ((start (point)))
      (ru-lang-forward-list)
      (should (looking-at "。\n"))
      (ru-lang-backward-list)
      (should (= (point) start)))))

(ert-deftest ru-lang-anonymous-navigation-interleaves-parentheses ()
  (ru-lang-test--buffer "显 ((算 值 为 数:\n得 值.\n法) 4).\n"
    (search-forward "得 值")
    (ru-lang-backward-up-list)
    (should (looking-at "算 值"))
    (ru-lang-forward-list)
    (should (looking-at ") 4)"))
    (ru-lang-backward-up-list)
    (should (looking-at "(算"))
    (ru-lang-forward-list)
    (should (looking-at " 4)"))
    (ru-lang-backward-up-list)
    (should (looking-at "((算"))))

(ert-deftest ru-lang-anonymous-comments-fullwidth-and-reference-compatibility ()
  (ru-lang-test--indent
   "回调 取 算 # 参数\n值 为 数：\n得 值。\n法。\n报到 取 作 // 零参\n：\n显 ‘算 值 为 数: 法’。\n为。\n副本 取 算 （回调）。\n算 模块 其 平方。\n作 对象@输出。\n"
   "回调 取 算 # 参数\n    值 为 数：\n    得 值。\n法。\n报到 取 作 // 零参\n    ：\n    显 ‘算 值 为 数: 法’。\n为。\n副本 取 算 （回调）。\n算 模块 其 平方。\n作 对象@输出。\n"))

(ert-deftest ru-lang-anonymous-compact-procedure-and-conversion-boundaries ()
  (ru-lang-test--indent
   "作 主:\n输出 取 作 值 为 数: 显 值 为 句. 为.\n输出 3.\n显 (算: 得 1. 法)() 为 句.\n为\n显 '完成'.\n"
   "作 主:\n    输出 取 作 值 为 数: 显 值 为 句. 为.\n    输出 3.\n    显 (算: 得 1. 法)() 为 句.\n为\n显 '完成'.\n"))

(ert-deftest ru-lang-anonymous-header-token-kinds-and-standalone-body ()
  (ru-lang-test--buffer "显 算 回声 '为'.\n显 作 回声 ':'.\n显 算 回声 形参 '为'.\n作: x 为 数. 为.\n"
    (font-lock-ensure)
    (let ((blocks (ru-lang--navigation-blocks t)))
      (should (= (length blocks) 1))
      (should (ru-lang--block-literal (car blocks)))
      (should (ru-lang--block-closed (car blocks))))
    (should-not (ru-lang-imenu-create-index))
    (let ((original (buffer-string)))
      (indent-region (point-min) (point-max))
      (should (equal original (buffer-string))))))

(ert-deftest ru-lang-anonymous-reference-conversions-do-not-open-blocks ()
  (ru-lang-test--buffer "显 算 f 为 句.\n列表 取 作 输出 为 阵.\n显 算 列[0] 为 句.\n回调 取 算 值 为 数 阵, 操作 为 作, : 得 值. 法.\n"
    (font-lock-ensure)
    (search-forward "f")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
    (should (= (length (ru-lang--navigation-blocks t)) 1))
    (should (ru-lang--block-literal (car (ru-lang--navigation-blocks t))))
    (should-not (ru-lang-imenu-create-index))
    (let ((original (buffer-string)))
      (indent-region (point-min) (point-max))
      (should (equal original (buffer-string))))))

(ert-deftest ru-lang-anonymous-all-editing-prefixes ()
  (let ((source "算 工厂 初值 为 数:\n当前 取 初值.\n得 [算 步 为 数: 当前 取 当前+步. 得 当前. 法,作: 显 当前. 为].\n法\n显 ((算 值 为 数: 得 值. 法) 3).\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-imenu-create-index)
        (ru-lang-beginning-of-defun)
        (ru-lang-end-of-defun)
        (ru-lang-forward-block 3)
        (ru-lang-backward-block 3)
        (ru-lang-up-block)))))


(defmacro ru-lang-test--run-file (source &rest body)
  "Create a temporary source file containing SOURCE and evaluate BODY."
  (declare (indent 1))
  `(let* ((directory (make-temp-file "ru run 中文 " t))
          (file (expand-file-name "源 ' ; $ file.ru" directory))
          (ru-lang-run-command nil))
     (unwind-protect
         (progn
           (with-temp-file file (insert ,source))
           (with-current-buffer (find-file-noselect file)
             (cl-letf (((symbol-function 'display-buffer) #'ignore))
               ,@body)))
       (let* ((output (get-buffer (ru-lang--run-buffer-name file)))
              (process (and output (get-buffer-process output))))
         (when (process-live-p process) (delete-process process))
         (when output (kill-buffer output)))
       (when-let ((source-buffer (get-file-buffer file)))
         (with-current-buffer source-buffer (set-buffer-modified-p nil))
         (kill-buffer source-buffer))
       (delete-directory directory t))))

(defun ru-lang-test--await-run (output)
  "Wait at most ten seconds for OUTPUT's process, and return its exit code."
  (let ((process (get-buffer-process output))
        (deadline (+ (float-time) 10)))
    (should process)
    (while (and (process-live-p process) (< (float-time) deadline))
      (accept-process-output process 0.05))
    (should-not (process-live-p process))
    (accept-process-output process 0.05)
    (process-exit-status process)))

(ert-deftest ru-lang-run-keybinding ()
  (should (eq (lookup-key ru-lang-mode-map (kbd "C-c C-r"))
              #'ru-lang-run-file)))

(ert-deftest ru-lang-run-requires-visited-local-file ()
  (with-temp-buffer
    (should-error (ru-lang-run-file) :type 'user-error)
    (setq buffer-file-name "/ssh:example:/tmp/a.ru")
    (should-error (ru-lang-run-file) :type 'user-error)))

(ert-deftest ru-lang-run-declined-save-does-not-run-stale-source ()
  (ru-lang-test--run-file "显 '旧'."
    (insert "# changed\n")
    (cl-letf (((symbol-function 'y-or-n-p) (lambda (&rest _) nil)))
      (should-error (ru-lang-run-file) :type 'user-error))
    (should (buffer-modified-p))
    (should-not (get-buffer (ru-lang--run-buffer-name file)))))

(ert-deftest ru-lang-run-save-and-unicode-shell-metacharacters ()
  (ru-lang-test--run-file "显 '旧'."
    (erase-buffer)
    (insert "显 '新结果'.")
    (cl-letf (((symbol-function 'y-or-n-p) (lambda (&rest _) t)))
      (let ((output (ru-lang-run-file)))
        (should-not (buffer-modified-p))
        (should (= 0 (ru-lang-test--await-run output)))
        (with-current-buffer output
          (should (derived-mode-p 'comint-mode))
          (should (equal default-directory (file-name-as-directory directory)))
          (should (string-match-p "新结果" (buffer-string))))))))

(ert-deftest ru-lang-run-save-failure-aborts ()
  (ru-lang-test--run-file "显 1."
    (insert "# changed\n")
    (cl-letf (((symbol-function 'y-or-n-p) (lambda (&rest _) t))
              ((symbol-function 'save-buffer) #'ignore))
      (should-error (ru-lang-run-file) :type 'user-error))
    (should-not (get-buffer (ru-lang--run-buffer-name file)))))

(ert-deftest ru-lang-run-invalid-command-and-missing-cli ()
  (ru-lang-test--run-file "显 1."
    (dolist (command '("python3" ("") (17) ("ru-no-such-executable-12345")))
      (let ((ru-lang-run-command command))
        (should-error (ru-lang-run-file) :type 'user-error)))
    (let ((ru-lang--bundled-cli (expand-file-name "missing-cli" directory)))
      (should-error (ru-lang-run-file) :type 'user-error))
    (should-not (get-buffer (ru-lang--run-buffer-name file)))))

(ert-deftest ru-lang-run-custom-command-preserves-argv ()
  (ru-lang-test--run-file "显 1."
    (let* ((ru-lang-run-command '("python3" "-u" "custom cli" "--flag"))
           (default-directory ru-lang-test--root)
           captured checked-directory)
      (cl-letf (((symbol-function 'make-comint-in-buffer)
                 (lambda (&rest args) (setq captured args)))
                ((symbol-function 'executable-find)
                 (lambda (_)
                   (setq checked-directory default-directory)
                   t)))
        (ru-lang-run-file))
      (should (equal checked-directory (file-name-as-directory directory)))
      (should (equal (nthcdr 2 captured)
                     (list "python3" nil "-u" "custom cli" "--flag" "run" file))))))

(ert-deftest ru-lang-run-source-must-exist ()
  (ru-lang-test--run-file "显 1."
    (delete-file file)
    (should-error (ru-lang-run-file) :type 'user-error)
    (should-not (get-buffer (ru-lang--run-buffer-name file)))))

(ert-deftest ru-lang-run-errors-and-rerun ()
  (ru-lang-test--run-file "卒 '失败标记'."
    (let ((output (ru-lang-run-file)))
      (should (= 1 (ru-lang-test--await-run output)))
      (with-current-buffer output
        (should (string-match-p "失败标记" (buffer-string)))))
    (erase-buffer)
    (insert "显 '再次成功'.")
    (save-buffer)
    (let ((output (ru-lang-run-file)))
      (should (= 0 (ru-lang-test--await-run output)))
      (with-current-buffer output
        (should (string-match-p "再次成功" (buffer-string)))))))

(ert-deftest ru-lang-run-stdin-and-live-process-protection ()
  (ru-lang-test--run-file "显 读."
    (let* ((output (ru-lang-run-file))
           (process (get-buffer-process output)))
      (should (process-live-p process))
      (should-error (ru-lang-run-file) :type 'user-error)
      (should (eq process (get-buffer-process output)))
      (process-send-string process "输入成功\n")
      (should (= 0 (ru-lang-test--await-run output)))
      (with-current-buffer output
        (should (string-match-p "输入成功" (buffer-string)))))))

(ert-deftest ru-lang-run-distinct-file-output-buffers ()
  (should-not (equal (ru-lang--run-buffer-name "/tmp/one/main.ru")
                     (ru-lang--run-buffer-name "/tmp/two/main.ru"))))

(ert-deftest ru-lang-run-module-relative-to-source ()
  (ru-lang-test--run-file "模 取 外言 '模块.ru'. 显 模 其 值."
    (with-temp-file (expand-file-name "模块.ru" directory)
      (insert "值 取 42."))
    (let ((output (ru-lang-run-file)))
      (should (= 0 (ru-lang-test--await-run output)))
      (with-current-buffer output
        (should (string-match-p "42" (buffer-string)))))))

(provide 'ru-lang-mode-tests)
;;; ru-lang-mode-tests.el ends here

(ert-deftest ru-lang-chinese-comments ()
  (ru-lang-test--buffer "批. 算 假:\n批评 取 1. 解释 取 2.\n解。 \"\n解. 若 1 则 foo释.\n显 1. 批。 为\n"
    (ru-lang--ensure-cache)
    (should (= (length ru-lang--blocks) 0))
    (should (= (length (seq-filter (lambda (token) (eq (ru-lang--token-kind token) 'comment)) ru-lang--tokens)) 3))
    (syntax-propertize (point-max))
    (goto-char (point-min)) (search-forward "假")
    (should (nth 4 (syntax-ppss)))
    (search-forward "foo") (should (nth 4 (syntax-ppss)))
    (search-forward "显") (should-not (nth 4 (syntax-ppss)))
    (goto-char (point-min)) (search-forward "取")
    (should (string-match-p "不隐式改写模块变量" (get-text-property (1- (point)) 'help-echo)))))

(ert-deftest ru-lang-chinese-comment-indent-and-incomplete ()
  (ru-lang-test--indent
   "作 名:\n解. 若\n  原样\n释.\n显 1. 批. 为\n为"
   "作 名:\n    解. 若\n  原样\n释.\n    显 1. 批. 为\n为")
  (ru-lang-test--buffer "解. \" 未闭合\n若 1 则"
    (syntax-propertize (point-max))
    (goto-char (point-max))
    (should (nth 4 (syntax-ppss)))
    (should-not (ru-lang--navigation-blocks nil))))

(ert-deftest ru-lang-procedure-finish-is-not-a-closer ()
  (ru-lang-test--indent
   "作 提前:\n若 1 则\n完。\n然\n完.\n完成 取 1.\n为"
   "作 提前:\n    若 1 则\n        完。\n    然\n    完.\n    完成 取 1.\n为")
  (ru-lang-test--buffer "作 提前:\n若 1 则\n完。\n然\n完.\n完成 取 1.\n为"
    (font-lock-ensure)
    (search-forward "完。")
    (should (eq (get-text-property (- (point) 2) 'face) 'font-lock-keyword-face))
    (ru-lang-up-block)
    (should (looking-at "若"))
    (ru-lang-forward-block)
    (should (eq (char-before) ?然))
    (ru-lang-forward-block)
    (should (eq (char-before) ?为))
    (goto-char (point-min))
    (search-forward "完成")
    (should-not (get-text-property (- (point) 2) 'face))
    (goto-char (point-min))
    (ru-lang-end-of-defun)
    (should (eq (char-before) ?为))))

(ert-deftest ru-lang-procedure-finish-strings-and-comments ()
  (ru-lang-test--buffer "作 提前:\n显 '完。'. # 完.\n批. 完。\n解. 完. 释.\n完.\n为"
    (font-lock-ensure)
    (search-forward "完。")
    (should (eq (get-text-property (- (point) 2) 'face) 'font-lock-string-face))
    (search-forward "完.")
    (should (eq (get-text-property (- (point) 2) 'face) 'font-lock-comment-face))
    (goto-char (point-min))
    (ru-lang-forward-block)
    (should (eq (char-before) ?为))))

(ert-deftest ru-lang-optional-parameter-annotations-indent ()
  (ru-lang-test--indent
   "算 保留 值, 次数 为 数, 后:\n得 值.\n法\n副本 取 算 值，次数 为 数 后：\n得 值.\n法。\n作 输出 值:\n回 取 作 参数:\n显 参数.\n为.\n为\n引用 取 算 保留.\n转换 取 算 保留 为 句.\n"
   "算 保留 值, 次数 为 数, 后:\n    得 值.\n法\n副本 取 算 值，次数 为 数 后：\n    得 值.\n法。\n作 输出 值:\n    回 取 作 参数:\n        显 参数.\n    为.\n为\n引用 取 算 保留.\n转换 取 算 保留 为 句.\n"))

(ert-deftest ru-lang-optional-parameter-annotations-faces-and-imenu ()
  (ru-lang-test--buffer "算 保留 值: 得 值. 法\n回 取 算 参数, 次数 为 数: 得 参数. 法.\n作 输出 参数: 显 参数. 为\n"
    (font-lock-ensure)
    (should (equal (mapcar #'car (ru-lang-imenu-create-index)) '("算 保留" "作 输出")))
    (search-forward "保留")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-function-name-face))
    (search-forward "取 算 参数")
    (should-not (get-text-property (1- (point)) 'face))
    (search-forward "为 数")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (should (= (length (ru-lang--navigation-blocks t)) 3))
    (should (cl-every #'ru-lang--block-closed (ru-lang--navigation-blocks t)))))

(ert-deftest ru-lang-optional-parameter-annotations-all-prefixes ()
  (let ((source "算 保留 值, 次数 为 数:\n得 算 左，右 为 数 后：\n得 左.\n法.\n法\n回 取 作 # 参数\n值：\n完.\n为。\n引用 取 算 保留 为 句.\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (ru-lang-imenu-create-index)
        (indent-region (point-min) (point-max))))))

(ert-deftest ru-lang-optional-headers-preserve-named-reference-calls ()
  (dolist (source '("算 回 值:1." "显 算 回 值:1." "引用 取 作 回 值:空."))
    (ru-lang-test--buffer source
      (should-not (ru-lang--navigation-blocks t))
      (should-not (ru-lang-imenu-create-index))))
  (ru-lang-test--buffer "回 取 算 值:"
    (should (= (length (ru-lang--navigation-blocks t)) 1))))

(ert-deftest ru-lang-named-reference-before-independent-definition ()
  (ru-lang-test--buffer "算 回 值:1.\n算 其他 参数: 得 参数. 法\n显 算 回 值:1.\n作 输出 值: 显 值. 为"
    (should (equal (mapcar #'car (ru-lang-imenu-create-index)) '("算 其他" "作 输出")))
    (should (cl-every #'ru-lang--block-closed (ru-lang--navigation-blocks t))))
  (ru-lang-test--buffer (apply #'concat (make-list 1000 "算 返回 值: 值. 法\n"))
    (should (= (length (ru-lang--navigation-blocks t)) 1000))))

(ert-deftest ru-lang-maps-and-facts-faces ()
  (ru-lang-test--buffer "值 为 事实 取 真. 表 为 典 取 典: 1 对 假. 成. 假设 取 1. 成果 取 2. 典籍 取 3."
    (font-lock-ensure)
    (search-forward "事实")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (search-forward "真")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (should (get-text-property (1- (point)) 'help-echo))
    (search-forward "为 典")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (search-forward "取 典")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (dolist (word '("假设" "成果" "典籍"))
      (search-forward word)
      (should-not (get-text-property (1- (point)) 'face)))
    (should (= (length (ru-lang--navigation-blocks nil)) 1))))

(ert-deftest ru-lang-maps-nested-callback-and-fullwidth-indent ()
  (ru-lang-test--indent
   "资料 取 典：\n‘设置’ 对 典：\n‘就绪’ 对 真。\n成。\n‘回调’ 对 算 值 为 事实：\n得 值。\n法。\n成。\n作 展示 数据 为 典：\n显 数据。\n为"
   "资料 取 典：\n    ‘设置’ 对 典：\n        ‘就绪’ 对 真。\n    成。\n    ‘回调’ 对 算 值 为 事实：\n        得 值。\n    法。\n成。\n作 展示 数据 为 典：\n    显 数据。\n为"))

(ert-deftest ru-lang-maps-navigation-keeps-outer-dot ()
  (ru-lang-test--buffer "表 取 典: '子' 对 典: 成. 成.\n"
    (search-forward "取 ")
    (let ((start (point)))
      (ru-lang-forward-list)
      (should (looking-at "\\.\n"))
      (ru-lang-backward-list)
      (should (= start (point)))
      (search-forward "子")
      (ru-lang-backward-up-list)
      (should (= start (point))))
    (should-not (ru-lang-imenu-create-index))))

(ert-deftest ru-lang-maps-types-references-and-prefixes ()
  (ru-lang-test--buffer "算 回 值:真. 算 回 值:假. 算 回 值:典: 成."
    (should-not (ru-lang--navigation-blocks t)))
  (ru-lang-test--indent
   "作 展示:\n显 值\n为 事实.\n显 值\n为 典.\n为"
   "作 展示:\n    显 值\n    为 事实.\n    显 值\n    为 典.\n为")
  (let ((source "空表 为 典.\n表 取 典: '回' 对 算 参数 为 典: 得 参数. 法. 成.\n"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-imenu-create-index)
        (condition-case nil
            (progn (ru-lang-forward-list) (ru-lang-backward-list))
          (user-error nil))))))


(ert-deftest ru-lang-symbolic-maps-nested-indent ()
  (ru-lang-test--indent
   "表 取 {\n'子': 典:\n'阵' 对 [｛｝, {}].\n成,\n'回': 算 值:\n得 {'值': 值}.\n法,\n}."
   "表 取 {\n    '子': 典:\n        '阵' 对 [｛｝, {}].\n    成,\n    '回': 算 值:\n        得 {'值': 值}.\n    法,\n}."))

(ert-deftest ru-lang-symbolic-maps-navigation-and-syntax ()
  (dolist (source '("表 取 {'子': ｛｝,}.\n" "表 取 ｛'子'：{}，｝。\n"))
    (ru-lang-test--buffer source
      (search-forward "取 ")
      (let ((start (point)))
        (ru-lang-forward-list)
        (should (looking-at "[.。]\n"))
        (ru-lang-backward-list)
        (should (= start (point)))
        (forward-sexp)
        (should (looking-at "[.。]\n"))
        (goto-char start)
        (search-forward "子")
        (ru-lang-backward-up-list)
        (should (= start (point))))
      (should-not (ru-lang-imenu-create-index))
      (should-not (ru-lang--navigation-blocks nil)))))

(ert-deftest ru-lang-symbolic-maps-faces-and-opaque-text ()
  (ru-lang-test--buffer "表 为 典 取 ｛'真'：真，'回'：算 值: 得 值. 法，｝。\n显 '{成}'. # ｛\n解. } 释."
    (font-lock-ensure)
    (search-forward "典")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-type-face))
    (search-forward "：真")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-keyword-face))
    (search-forward "算 值")
    (should-not (get-text-property (1- (point)) 'face))
    (should-not (ru-lang-imenu-create-index))
    (should (= (length ru-lang--structures) 2))
    (should (cl-every #'ru-lang--block-closed ru-lang--structures))))

(ert-deftest ru-lang-symbolic-maps-references-and-prefixes ()
  (ru-lang-test--buffer "算 回 值:{}. 显 算 回 值:｛1：真｝. 引用 取 作 回 值:{1:2,}."
    (should-not (ru-lang--navigation-blocks t))
    (should (= (length ru-lang--structures) 3))
    (should (cl-every #'ru-lang--block-closed ru-lang--structures)))
  (let ((source "表 为 典 取 {\n'回': 算 值: 得 ｛'值': 值｝. 法,\n'子': 典: 1 对 {}. 成,\n}."))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-imenu-create-index)
        (condition-case nil
            (progn (ru-lang-forward-list) (ru-lang-backward-list))
          (user-error nil))))))

(ert-deftest ru-lang-scoped-blocks-indent-and-expression-maps ()
  (ru-lang-test--indent
   "段：\n落 := 2.\n｛\n表 ：= {'值': 落}.\n显 表.\n｝\n落。\n显 {}.\n({}).\n{}"
   "段：\n    落 := 2.\n    ｛\n        表 ：= {'值': 落}.\n        显 表.\n    ｝\n落。\n显 {}.\n({}).\n{}"))

(ert-deftest ru-lang-scoped-contextual-names-and-help ()
  (ru-lang-test--buffer "段 := 1. 落 取 2. 段落 取 3. 落叶 取 4.\n段:\n落 取 落+1.\n显 文 其 段 始:0 终:2.\nf 段: {} 落: 2.\n落 ."
    (font-lock-ensure)
    (dolist (word '("段" "落" "段落" "落叶"))
      (search-forward word)
      (should-not (get-text-property (1- (point)) 'face)))
    (search-forward "段:")
    (should (eq (get-text-property (- (point) 2) 'face) 'font-lock-keyword-face))
    (should (get-text-property (- (point) 2) 'help-echo))
    (search-forward "落 取")
    (should-not (get-text-property (- (point) 3) 'face))
    (search-forward "其 段")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-builtin-face))
    (should-not (get-text-property (1- (point)) 'help-echo))
    (should (cl-every #'ru-lang--block-closed ru-lang--structures))
    (should (= (length (cl-remove-if-not #'ru-lang--block-scoped ru-lang--structures)) 1))))

(ert-deftest ru-lang-scoped-navigation-and-imenu ()
  (dolist (source '("段: 算 内: 得 {}. 法 落.\n" "{ 算 内: 得 {}. 法 }.\n"))
    (ru-lang-test--buffer source
      (let ((start (point)))
        (ru-lang-forward-list)
        (should (looking-at "\n"))
        (ru-lang-backward-list)
        (should (= start (point)))
        (search-forward "得 ")
        (ru-lang-forward-list)
        (should (looking-at "\\.")))
      (should (equal (mapcar #'car (ru-lang-imenu-create-index)) '("算 内")))
      (should (= (length (ru-lang--navigation-blocks nil)) 2))
      (should (= (length ru-lang--structures) 3)))))

(ert-deftest ru-lang-scoped-closer-requires-punctuation-dot ()
  (dolist (source '("段: 落" "段: 落 '.'" "段: 落 取 2." "段: 落 := 2."))
    (ru-lang-test--buffer source
      (should-not (ru-lang--block-closed (car (ru-lang--navigation-blocks nil))))))
  (ru-lang-test--buffer "段 # 开头\n：\n落 # 结束\n。"
    (should (ru-lang--block-closed (car (ru-lang--navigation-blocks nil)))))
  (ru-lang-test--buffer "试 卒 '原因'. 救 段: 显 段. 终."
    (font-lock-ensure)
    (search-forward "救 段")
    (should (eq (get-text-property (1- (point)) 'face) 'font-lock-variable-name-face))
    (should (= (length (ru-lang--navigation-blocks nil)) 1))))

(ert-deftest ru-lang-assignment-aliases-tokenization-and-help ()
  (ru-lang-test--buffer "段:=1. 落：=2. 表 := {'键': 1}. 表['键'] := 2. 显 ':='。 # ：=\n解. := 释."
    (font-lock-ensure)
    (let ((aliases (cl-remove-if-not
                    (lambda (token) (equal (ru-lang--token-text token) ":="))
                    (append ru-lang--tokens nil))))
      (should (= (length aliases) 4))
      (dolist (token aliases)
        (should (eq (ru-lang--token-kind token) 'punct))
        (should (eq (ru-lang--token-face token) 'font-lock-keyword-face))
        (should (equal (get-text-property (ru-lang--token-start token) 'help-echo)
                       ru-lang--assignment-help))))
    (should-not (cl-find-if #'ru-lang--block-scoped ru-lang--structures)))
  (ru-lang-test--buffer ": = ：＝"
    (ru-lang--ensure-cache)
    (should (equal (mapcar #'ru-lang--token-text (append ru-lang--tokens nil))
                   '(":" "=" ":" "＝")))))

(ert-deftest ru-lang-scoped-all-prefixes-and-opaque-text ()
  (ru-lang-test--buffer "显 '段: 落. {}'. # 段: 落.\n解. { } 释."
    (should-not (ru-lang--navigation-blocks nil)))
  (let ((source "作 主:\n循 2 次\n段：\n落 ：= 2.\n{\n回 := 算 值: 得 {'值': 值}. 法.\n回 值: {}.\n}\n落。\n环\n为"))
    (dotimes (end (1+ (length source)))
      (ru-lang-test--buffer (substring source 0 end)
        (font-lock-ensure)
        (indent-region (point-min) (point-max))
        (let ((once (buffer-string)))
          (indent-region (point-min) (point-max))
          (should (equal once (buffer-string))))
        (ru-lang-imenu-create-index)
        (condition-case nil
            (progn (ru-lang-forward-list) (ru-lang-backward-list))
          (user-error nil))))))

(ert-deftest ru-practical-members-and-library-names ()
  (dolist (name '("删" "弹" "查"))
    (should (member name ru-lang--member-builtins)))
  (dolist (name '("拆分" "替换" "去空白" "定点" "平方根" "幂" "造源"))
    (should-not (member name ru-lang--builtins))))

(ert-deftest ru-dictionary-named-parameter-help ()
  (dolist (entry '(("查" . "典：查 目:") ("增" . "典：增 目: 相:") ("除" . "典：除 目:")))
    (should (string-match-p (regexp-quote (cdr entry))
                            (cdr (assoc (car entry) ru-lang--practical-member-help)))))

(ert-deftest ru-lang-diagnostic-paths-and-legacy-format ()
  (dolist (file '("C:\\中文 目录\\题目.ru" "/tmp/空 格/😀.ru" "C:/中文/题.ru"))
    (dolist (prefix '("error: " ""))
      (should (string-match ru-lang--diagnostic-regexp
                            (format "%s:12:3: %s运行错误：测试" file prefix)))
      (should (equal (match-string 1 (format "%s:12:3: %s运行错误：测试" file prefix)) file)))))

(ert-deftest ru-lang-diagnostic-codepoint-navigation ()
  ;; A TAB, Chinese BMP character, and non-BMP character each count as one.
  (let* ((file (make-temp-file "如诊断 空格 " nil ".ru" "\t中文😀目标\n"))
         (source-buffer (find-file-noselect file)))
    (unwind-protect
        (with-temp-buffer
          (comint-mode)
          (ru-lang--enable-run-diagnostics (point-min))
          (insert (format "%s:1:5: error: 运行错误：定位\n" file))
          (save-window-excursion
            (compilation-next-error-function 1 t)
            (with-current-buffer source-buffer
              (should (= (point) 5))
              (should (eq (char-after) ?目)))))
      (when (buffer-live-p source-buffer) (kill-buffer source-buffer))
      (delete-file file))))

(ert-deftest ru-lang-diagnostic-virtual-sources-are-not-files ()
  (with-temp-buffer
    (comint-mode)
    (ru-lang--enable-run-diagnostics (point-min))
    (insert "rushu://session/1/cell/2.ru:1:1: error: 虚拟来源\n<cell>:1:1: error: 虚拟来源\n")
    (should-error (compilation-next-error-function 1 t) :type 'user-error)))

(ert-deftest ru-lang-diagnostic-keeps-comint-input-bindings ()
  (with-temp-buffer
    (comint-mode)
    (ru-lang--enable-run-diagnostics (point-min))
    (should (derived-mode-p 'comint-mode))
    (should compilation-shell-minor-mode)
    (should (eq (key-binding (kbd "RET")) #'comint-send-input))
    (should (eq (key-binding (kbd "C-c C-c")) #'comint-interrupt-subjob))
    (should (eq (key-binding (kbd "C-c C-d")) #'comint-delchar-or-maybe-eof))
    (should-not compilation-error-screen-columns)
    (should (= compilation-first-column 1))))

(ert-deftest ru-lang-diagnostic-line-only-and-colon-paths ()
  (dolist (file '("C:\\中文 目录\\题目.ru" "/tmp/中文:片段 文件.ru"))
    (dolist (location '("12" "12:3"))
      (dolist (prefix '("error: " ""))
        (let ((diagnostic (format "%s:%s: %s运行错误：测试" file location prefix)))
          (should (string-match ru-lang--diagnostic-regexp diagnostic))
          (should (equal (match-string 1 diagnostic) file))
          (should (equal (match-string 2 diagnostic) "12"))
          (should (equal (match-string 3 diagnostic)
                         (and (equal location "12:3") "3"))))))))

(ert-deftest ru-lang-canonical-module-imports-stay-strings ()
  (dolist (module '("如:竞" "如:观"))
    (dolist (quotes '(("'" . "'") ("\"" . "\"") ("‘" . "’") ("“" . "”")))
      (let ((literal (concat (car quotes) module (cdr quotes))))
        (ru-lang-test--buffer (concat "模块 取 外言 " literal ".\n显 '完成'.")
          (font-lock-ensure)
          (search-forward "外言")
          (let ((help (get-text-property (1- (point)) 'help-echo)))
            (should (string-match-p "如:竞" help))
            (should (string-match-p "如:观" help))
            (should (string-match-p "无兼容别名" help)))
          (search-forward ":")
          (should (eq (get-text-property (1- (point)) 'face) 'font-lock-string-face))
          (ru-lang--ensure-cache)
          (should (seq-find (lambda (token)
                              (and (eq (ru-lang--token-kind token) 'string)
                                   (equal (ru-lang--token-text token) literal)))
                            ru-lang--tokens))
          (should-not (seq-find (lambda (token) (equal (ru-lang--token-text token) ":"))
                               ru-lang--tokens)))))))


(ert-deftest ru-array-sort-map-contextual-help ()
  (dolist (name '("排序" "另成" "逐位" "逐目"))
    (should (member name ru-lang--member-builtins))
    (should-not (member name ru-lang--builtins))
    (should (assoc name ru-lang--practical-member-help)))
  (should (string-match-p "先于:二参算" (cdr (assoc "排序" ru-lang--practical-member-help))))
  (should (string-match-p "不接受作" (cdr (assoc "另成" ru-lang--practical-member-help)))))

(ert-deftest ru-graphics-upgrade-contextual-members ()
  (dolist (name '("三角形" "多边形" "平移" "旋转" "缩放" "保存" "恢复" "变换" "重置变换" "裁剪" "取消裁剪"))
    (should (member name ru-lang--member-builtins))
    (should-not (member name ru-lang--keywords))
    (should-not (member name ru-lang--builtins))))
