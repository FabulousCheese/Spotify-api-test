pipeline {
    agent any

    environment {
        LLM_API_KEY     = credentials('deepseek-api-key')
        LLM_API_BASE    = 'https://api.deepseek.com'
        LLM_MODEL       = 'deepseek-chat'
        CLIENT_ID       = credentials('spotify-client-id')
        CLIENT_SECRET   = credentials('spotify-client-secret')
        PASS_THRESHOLD  = '80'
        MAX_REVIEW_RETRIES = '2'
    }

    // 全局变量：是否已有测试用例（用于跳过 LLM 生成）
    // 全局变量：最终通过率

    stages {

        stage('环境准备 & 检测已有用例') {
            steps {
                script {
                    sh '''
                        python3 -m venv venv
                        . venv/bin/activate
                        pip install -r requirements.txt
                        echo "ClientId=${CLIENT_ID}" > .env
                        echo "Secret=${CLIENT_SECRET}" >> .env
                        echo "LLM_API_KEY=${LLM_API_KEY}" >> .env
                        echo "LLM_API_BASE=${LLM_API_BASE}" >> .env
                        echo "LLM_MODEL=${LLM_MODEL}" >> .env
                    '''

                    // 检测是否已有测试用例（避免重复调用 LLM 花钱）
                    env.HAS_TESTS = sh(
                        script: '''
                            test -f test_data/albums.yaml \
                            && test -f tests/test_stateful_workflows.py \
                            && echo "true" || echo "false"
                        ''',
                        returnStdout: true
                    ).trim()

                    if (env.HAS_TESTS == 'true') {
                        echo '✅ 已有测试用例，跳过 LLM 生成阶段'
                    } else {
                        echo '⚠️  未找到测试用例，将调用 LLM 生成'
                    }
                }
            }
        }

        stage('① 提取 & 分类端点') {
            steps {
                sh '. venv/bin/activate && python extract_api.py'
                sh '. venv/bin/activate && python classify_endpoints.py'
            }
        }

        stage('② LLM 生成测试用例') {
            when { expression { env.HAS_TESTS != 'true' } }
            steps {
                echo '🤖 调用 DeepSeek 生成数据驱动 YAML ...'
                sh '. venv/bin/activate && python generate_data_yaml.py'

                echo '🤖 调用 DeepSeek 生成有状态链路测试 ...'
                sh '. venv/bin/activate && python generate_tests.py --mode stateful'
            }
        }

        stage('③ LLM 专家审查 & 改进') {
            steps {
                script {
                    echo '🔍 LLM 测试专家审查中...'
                    def reviewExit = sh(
                        script: '. venv/bin/activate && python review_and_improve.py',
                        returnStatus: true
                    )

                    if (reviewExit == 0) {
                        echo '✅ 审查通过：测试用例质量达标'
                    } else {
                        echo '⚠️  审查完成，部分问题可能仍需手动处理'
                    }
                }
            }
        }

        stage('④ 执行测试') {
            steps {
                script {
                    echo '🚀 执行全部测试...'
                    def testExit = sh(
                        script: '. venv/bin/activate && python run_pipeline.py --fast',
                        returnStatus: true
                    )

                    // 解析通过率
                    env.PASS_RATE = sh(
                        script: '''. venv/bin/activate && python -c "
import subprocess, sys, re
r = subprocess.run([sys.executable, '-m', 'pytest', 'tests/', '--tb=no', '-q'],
                   capture_output=True, text=True)
m = re.search(r'(\d+)\s+passed', r.stdout)
passed = int(m.group(1)) if m else 0
m = re.search(r'(\d+)\s+failed', r.stdout)
failed = int(m.group(1)) if m else 0
m = re.search(r'(\d+)\s+skipped', r.stdout)
skipped = int(m.group(1)) if m else 0
print(passed, skipped, failed)
"''',
                        returnStdout: true
                    ).trim()
                }
            }
            post {
                failure {
                    echo '⚠️  有测试失败，进入 AI 修复循环'
                }
            }
        }

        stage('⑤ 质量门禁 (≥ 80%)') {
            steps {
                script {
                    // PASS_RATE 格式: "37 19 0" → (passed skipped failed)
                    def parts = env.PASS_RATE.trim().split()
                    def p = parts[0].toInteger()
                    def s = parts[1].toInteger()
                    def f = parts[2].toInteger()
                    def total = p + f
                    def passPct = total > 0 ? (p * 100 / total).round(1) : 100

                    echo "通过率: ${passPct}% (${p} passed / ${total} total, ${s} skipped)"

                    if (passPct >= env.PASS_THRESHOLD.toInteger()) {
                        echo "✅ 通过率 ${passPct}% ≥ ${env.PASS_THRESHOLD}%"
                    } else {
                        error("❌ 通过率 ${passPct}% < ${env.PASS_THRESHOLD}%，质量门禁未通过")
                    }
                }
            }
        }

    }

    post {
        always {
            // Jenkins 原生测试报告
            junit 'reports/junit*.xml'

            // 归档审查历史
            archiveArtifacts artifacts: 'reports/review_history.json', fingerprint: true

            // 归档生成的测试用例
            archiveArtifacts artifacts: 'test_data/*.yaml', fingerprint: true

            // 构建摘要
            script {
                def summary = """
| 阶段 | 状态 |
|------|------|
| LLM 生成 | ${env.HAS_TESTS == 'true' ? '⏭ 跳过（已存在）' : '✅ 完成'} |
| 专家审查 | 见 reports/review_history.json |
| 测试执行 | 见测试报告页面 |
| 质量门禁 | ≥ ${env.PASS_THRESHOLD}% |

**产物**:
- `test_data/*.yaml` — YAML 测试数据
- `reports/junit*.xml` — JUnit 测试报告
- `reports/review_history.json` — LLM 审查历史
"""
                writeFile(file: 'reports/build_summary.md', text: summary)
            }
        }

        success {
            echo '🎉 流水线成功！测试用例质量达标。'
        }

        failure {
            echo '❌ 流水线失败。请检查测试报告和审查历史。'
            echo '提示：可手动运行 python review_and_improve.py 触发 LLM 修复'
        }
    }
}
