module REoptSolver

export run

using Base.Filesystem
#all solvers except for HiGHS are currently removed in order to improve precompile and load time
using REopt, JuMP, JSON, HiGHS #SCIP #, Cbc
#Ipopt, ECOS, Clp, GLPK

function get_model(path::String, max_runtime_s::Union{Nothing,Int}, tolerance::Float64, random_seed::Union{Nothing,Int}) 
	m = Model(HiGHS.Optimizer)
	set_attribute(m,"threads",20)
	set_attribute(m,"mip_rel_gap",tolerance)
    if max_runtime_s != nothing
        set_attribute(m,"time_limit", float(max_runtime_s))
    end
	if random_seed != nothing
		set_attribute(m,"random_seed", Int(random_seed))
	end
	return m
end

function results_to_json(results, output_path)
	j = JSON.json(results)

	open(output_path, "w") do file
		println(file, j)
	end
end

function run(path::String, outages::Bool=false, microgrid_only::Bool=false, max_runtime_s::Union{Nothing,Int}=nothing,
	api_key::String="WhEzm6QQQrks1hcsdN0Vrd56ZJmUyXJxTJFg6pn9", tolerance::Float64=0.05, random_seed::Union{Nothing,Int}=nothing)

	ENV["NREL_DEVELOPER_API_KEY"]=api_key

	m = get_model(path, max_runtime_s, tolerance, random_seed)
	m2 = get_model(path, max_runtime_s, tolerance, random_seed)
	input_path = normpath(joinpath(path, "Scenario_test_POST.json"))
	reopt_inputs_path = normpath(joinpath(path,"REoptInputs.json"))
	output_path = normpath(joinpath(path,"results.json"))

	#writing REoptInputs to JSON for easier access of default values in microgridDesign
	reopt_inputs = REoptInputs(input_path)
	results_to_json(reopt_inputs,reopt_inputs_path)

	results = run_reopt([m,m2],input_path)

	results_to_json(results, output_path)

	if outages != false
		outage_path = normpath(joinpath(path,"resultsResilience.json"))
		outage_results = simulate_outages(results, reopt_inputs; microgrid_only=microgrid_only)

		results_to_json(outage_results,outage_path)
	end

end

precompile(run, (String, Bool, Bool, Union{Nothing,Int}, String, Float64, Union{Nothing,Int},))

end 
