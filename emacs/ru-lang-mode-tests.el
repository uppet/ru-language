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

(provide 'ru-lang-mode-tests)
;;; ru-lang-mode-tests.el ends here
