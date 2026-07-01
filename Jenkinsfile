pipeline {
    agent any

    environment {
        LLM_API_KEY     = credentials('deepseek-api-key')
        LLM_API_BASE    = 'https://api.deepseek.com'
        LLM_MODEL       = 'deepseek-v4-pro'
        CLIENT_ID       = credentials('spotify-client-id')
        CLIENT_SECRET   = credentials('spotify-client-secret')
        PASS_THRESHOLD  = '80'
        MAX_REVIEW_RETRIES = '2'
    }

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
                sh '. venv/bin/activate && python cli.py extract'
                sh '. venv/bin/activate && python cli.py classify'
            }
        }

        stage('② LLM 生成测试用例') {
            when { expression { env.HAS_TESTS != 'true' } }
            steps {
                echo '🤖 调用 DeepSeek 生成 YAML 测试数据 ...'
                sh '. venv/bin/activate && python cli.py generate --mode data-driven'

                echo '🤖 调用 DeepSeek 生成有状态链路测试 ...'
                sh '. venv/bin/activate && python cli.py generate --mode stateful'
            }
        }

        stage('③ 单元测试（框架自测）') {
            steps {
                echo '🧪 运行框架自测 ...'
                sh '. venv/bin/activate && python -m pytest tests/unit/ -v'
            }
        }

        stage('④ LLM 专家审查 & 改进') {
            steps {
                script {
                    echo '🔍 LLM 测试专家审查中...'
                    def reviewExit = sh(
                        script: '. venv/bin/activate && python cli.py review',
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

        stage('⑤ 执行测试') {
            steps {
                script {
                    echo '🚀 执行全部测试...'
                    def testExit = sh(
                        script: '. venv/bin/activate && python cli.py run --fast',
                        returnStatus: true
                    )

                    def ciResult = readFile('reports/ci_result.txt').trim()
                    env.CI_RESULT = ciResult
                }
            }
            post {
                failure {
                    echo '⚠️  有测试失败，请检查测试报告'
                }
            }
        }

        stage('⑥ 质量门禁 (≥ 80%)') {
            steps {
                script {
                    def parts = env.CI_RESULT.split()
                    def p = parts[0].toInteger()
                    def s = parts[1].toInteger()
                    def f = parts[2].toInteger()
                    def total = p + f
                    def passPct = total > 0 ? Math.round(p * 100.0 / total * 10) / 10 : 100

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
            junit 'reports/junit*.xml'
            archiveArtifacts artifacts: 'reports/review_history.json', fingerprint: true
            archiveArtifacts artifacts: 'test_data/*.yaml', fingerprint: true

            script {
                sh '. venv/bin/activate && cp -f environment.xml reports/allure-results/ 2>/dev/null || true'
                allure includeProperties: false, report: 'reports/allure-report', results: [[path: 'reports/allure-results']]
            }

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
            echo '提示：可手动运行 python cli.py review 触发 LLM 修复'
        }
    }
}
