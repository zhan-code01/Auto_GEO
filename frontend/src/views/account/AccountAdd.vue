<template>
  <div class="account-add-placeholder">
    <el-empty description="请在账号列表页进行操作">
      <el-button type="primary" @click="$router.push('/accounts')">返回列表</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
.account-add-placeholder {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}
</style>