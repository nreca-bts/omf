using JSON
using Base.Filesystem

include(normpath(joinpath(@__DIR__, "REoptSolver", "src", "REoptSolver.jl")))

function test()
	json_data = JSON.parsefile(normpath(joinpath(string(@__DIR__), "testFiles","julia_default.json")))
	json_data["ElectricLoad"]["path_to_csv"] = normpath(joinpath(string(@__DIR__),"testFiles","loadShape.csv"))

    open(normpath(joinpath(string(@__DIR__), "testFiles","Scenario_test_POST.json")), "w") do file 
        JSON.print(file, json_data)
    end
	REoptSolver.run(normpath(joinpath(string(@__DIR__),"testFiles")), true)
end

test()
