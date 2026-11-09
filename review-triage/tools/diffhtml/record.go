package main

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// record は、記録 YAML のうち、案のパッチを取るのに要る項目だけを読んだもの。様式の SSOT は
// review-triage の record-schema.md。形の検査は triagecheck が行うので、ここでは行わない。
type record struct {
	Runs []struct {
		Plans []struct {
			ProblemID     string `yaml:"problem_id"`
			OptionPatches []struct {
				Option    string `yaml:"option"`
				Patch     string `yaml:"patch"`
				NoChange  bool   `yaml:"no_change"`
				CoveredBy *struct {
					ProblemID string `yaml:"problem_id"`
					Option    string `yaml:"option"`
				} `yaml:"covered_by"`
			} `yaml:"option_patches"`
		} `yaml:"plans"`
	} `yaml:"runs"`
}

func loadRecord(path string) (*record, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	rec, err := parseRecord(data)
	if err != nil {
		return nil, fmt.Errorf("記録 YAML を読めません (%s): %w", path, err)
	}
	return rec, nil
}

func parseRecord(data []byte) (*record, error) {
	var rec record
	if err := yaml.Unmarshal(data, &rec); err != nil {
		return nil, err
	}
	return &rec, nil
}

// patch は、マークが指す案のパッチを返す。
func (r *record) patch(m marker) (string, error) {
	where := fmt.Sprintf("%d 回目の %s の案 %s", m.run, m.problem, m.option)
	if m.run > len(r.Runs) {
		return "", fmt.Errorf("%s: 記録に %d 回目がありません (回は %d 回まで)", where, m.run, len(r.Runs))
	}
	for _, p := range r.Runs[m.run-1].Plans {
		if p.ProblemID != m.problem {
			continue
		}
		for _, o := range p.OptionPatches {
			if o.Option != m.option {
				continue
			}
			switch {
			case o.Patch != "":
				return o.Patch, nil
			case o.NoChange:
				return "", fmt.Errorf("%s: ファイルを変えない案 (no_change) で、パッチがありません", where)
			case o.CoveredBy != nil:
				return "", fmt.Errorf("%s: ほかの問題のパッチで覆う案 (covered_by: %s の案 %s) で、パッチがありません。参照先の節にリンクしてください", where, o.CoveredBy.ProblemID, o.CoveredBy.Option)
			}
			return "", fmt.Errorf("%s: パッチがありません", where)
		}
		return "", fmt.Errorf("%s: option_patches にこの案がありません", where)
	}
	return "", fmt.Errorf("%s: %d 回目の plans に %s がありません", where, m.run, m.problem)
}
