define void @ru_mi_kernel_0_llvm(i32* %out, i8* %p0, i32 %p0_length, i32 %p1_arg, i32 %p2_arg) {
entry:
  %l0 = alloca i32
  store i32 0, i32* %l0
  %l1 = alloca i8
  store i8 0, i8* %l1
  %counter9 = alloca i32
  store i32 %p1_arg, i32* %l0
  %t1 = icmp ult i32 %p2_arg, %p1_arg
  br i1 %t1, label %fail2, label %valid3
fail2:
  %t4 = getelementptr i32, i32* %out, i32 0
  store i32 2, i32* %t4, align 4
  %t5 = getelementptr i32, i32* %out, i32 1
  store i32 0, i32* %t5, align 4
  %t6 = getelementptr i32, i32* %out, i32 2
  store i32 4, i32* %t6, align 4
  %t7 = getelementptr i32, i32* %out, i32 3
  store i32 10, i32* %t7, align 4
  ret void
valid3:
  %t8 = sub i32 %p2_arg, %p1_arg
  store i32 0, i32* %counter9
  br label %test10
test10:
  %t14 = load i32, i32* %counter9
  %t15 = icmp ult i32 %t14, %t8
  br i1 %t15, label %loop11, label %endloop13
loop11:
  %t16 = load i32, i32* %l0
  %t17 = icmp uge i32 %t16, %p0_length
  br i1 %t17, label %fail18, label %valid19
fail18:
  %t20 = getelementptr i32, i32* %out, i32 0
  store i32 1, i32* %t20, align 4
  %t21 = getelementptr i32, i32* %out, i32 1
  store i32 0, i32* %t21, align 4
  %t22 = getelementptr i32, i32* %out, i32 2
  store i32 5, i32* %t22, align 4
  %t23 = getelementptr i32, i32* %out, i32 3
  store i32 15, i32* %t23, align 4
  ret void
valid19:
  %t24 = zext i32 %t16 to i64
  %t25 = getelementptr i8, i8* %p0, i64 %t24
  %t26 = load i8, i8* %t25, align 1
  store i8 %t26, i8* %l1
  %t27 = load i8, i8* %l1
  %t28 = icmp uge i8 %t27, 128
  br i1 %t28, label %logic30, label %rhs29
rhs29:
  %t31 = load i8, i8* %l1
  %t32 = icmp eq i8 %t31, 13
  br label %logic30
logic30:
  %t33 = phi i1 [%t28, %valid19], [%t32, %rhs29]
  br i1 %t33, label %logic35, label %rhs34
rhs34:
  %t36 = load i8, i8* %l1
  %t37 = icmp eq i8 %t36, 10
  br label %logic35
logic35:
  %t38 = phi i1 [%t33, %logic30], [%t37, %rhs34]
  br i1 %t38, label %logic40, label %rhs39
rhs39:
  %t41 = load i8, i8* %l1
  %t42 = icmp eq i8 %t41, 62
  br label %logic40
logic40:
  %t43 = phi i1 [%t38, %logic35], [%t42, %rhs39]
  br i1 %t43, label %yes44, label %no45
yes44:
  br label %endloop13
no45:
  br label %endif46
endif46:
  %t47 = load i32, i32* %l0
  %t48 = sub i32 4294967295, %t47
  %t49 = icmp ugt i32 1, %t48
  br i1 %t49, label %fail50, label %valid51
fail50:
  %t52 = getelementptr i32, i32* %out, i32 0
  store i32 2, i32* %t52, align 4
  %t53 = getelementptr i32, i32* %out, i32 1
  store i32 0, i32* %t53, align 4
  %t54 = getelementptr i32, i32* %out, i32 2
  store i32 9, i32* %t54, align 4
  %t55 = getelementptr i32, i32* %out, i32 3
  store i32 15, i32* %t55, align 4
  ret void
valid51:
  %t56 = add i32 %t47, 1
  store i32 %t56, i32* %l0
  br label %step12
step12:
  %t57 = add i32 %t14, 1
  store i32 %t57, i32* %counter9
  br label %test10
endloop13:
  %t58 = load i32, i32* %l0
  %t59 = icmp ult i32 %t58, %p1_arg
  br i1 %t59, label %fail60, label %valid61
fail60:
  %t62 = getelementptr i32, i32* %out, i32 0
  store i32 2, i32* %t62, align 4
  %t63 = getelementptr i32, i32* %out, i32 1
  store i32 0, i32* %t63, align 4
  %t64 = getelementptr i32, i32* %out, i32 2
  store i32 11, i32* %t64, align 4
  %t65 = getelementptr i32, i32* %out, i32 3
  store i32 9, i32* %t65, align 4
  ret void
valid61:
  %t66 = sub i32 %t58, %p1_arg
  %t67 = getelementptr i32, i32* %out, i32 0
  store i32 0, i32* %t67, align 4
  %t68 = getelementptr i32, i32* %out, i32 1
  store i32 %t66, i32* %t68, align 4
  %t69 = getelementptr i32, i32* %out, i32 2
  store i32 0, i32* %t69, align 4
  %t70 = getelementptr i32, i32* %out, i32 3
  store i32 0, i32* %t70, align 4
  ret void
}
