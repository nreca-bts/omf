"""
Implement the contextual source-separation core used by OMF solar disaggregation solver
wrappers.
"""

import numpy as np
# import cvxpy as cvp #cvxpy is a bad bad no good library and we only want to use it when we're using a model using this solver.

class CSSS:
### Contextually Supervised Source Seperation Class

    """
    Implement contextual source-separation state and optimization helpers.
    """
    def __init__(self, aggregateSignal):
        """
        Internal helper for csss init processing.
        """
        self.aggregateSignal  = aggregateSignal
        self.modelcounter     = 0   # Number of source signals
        self.models           = {}  # Model for each source signal, this is a list but could be a dict
        self.constraints      = []  # Additional constraints
        self.N                = len(aggregateSignal) # Length of aggregate signal

    def addSource(self, regressor, name = None,
                  costFunction='sse',alpha = 1,      # Cost function for fit to regressors, alpha is a scalar multiplier or a vector multiplier of length N
                  regularizeTheta=None, beta = 1,    # Cost function for parameter regularization, beta is a scalar multiplier
                  regularizeSource=None, gamma = 1,  # Cost function for signal smoothing, gamma is a scalar multiplier
                  lb = None, # Lower bound on source
                  ub = None  # Upper bound on source
                 ):
        """
        Implement add source behavior for CSSS instances.
        """
        import cvxpy as cvp #cvxpy is a bad bad no good library and we only want to use it when we're using a model using this solver.

        ### This is a method to add a new source
        self.modelcounter += 1   # Increment model counter

        ## Write model name if it doesn't exist.
        if name is None:
            name = str(self.modelcounter)

        ## Instantiate a dictionary of model terms
        model = {}
        model['name']  = name
        model['alpha'] = alpha
        model['lb']    = lb
        model['ub']    = ub

        ## Check regressor shape
        regressor = np.array(regressor)
        if regressor.ndim == 0: ## If no regressors are included, set them an empty array
            regressor = np.zeros((self.N,0))
        if regressor.ndim == 1:
            regressor = np.expand_dims(regressor,1)
        if regressor.ndim > 2:
            raise NameError('Regressors cannot have more than 2 dimensions')


        ## Check that regressors have the correct shape (Nobs, Nregressors)
        if regressor.shape[0] != self.N:
            if regressor.shape[1] == self.N:
                regressor = regressor.transpose()
            else:
                raise NameError('Lengths of regressors and aggregate signal must match')

        ## Define model regressors and order
        model['regressor'] = regressor
        model['order']     = regressor.shape[1]

        ## Define decision variables and cost function style
        model['source']    = cvp.Variable((self.N, 1))
        model['theta']     = cvp.Variable((model['order'], 1))
        model['costFunction'] = costFunction
        model['regularizeTheta'] = regularizeTheta
        model['beta'] = beta
        model['regularizeSource'] = regularizeSource
        model['gamma'] = gamma

        ## Append model to models list
        self.models[name]= model
        self.updateSourceObj(name)

    def updateSourceObj(self, sourcename):
        """
        Implement update source obj behavior for CSSS instances.
        """
        import cvxpy as cvp #cvxpy is a bad bad no good library and we only want to use it when we're using a model using this solver.
        if sourcename.lower() == 'all':
            for name in self.models.keys():
                self.updateSourceObj(name)
        else:
            model = self.models[sourcename]

            ## Define objective function to fit model to regressors
            ## **CHANGE MT: I moved the alpha variable to be inside the norms so that
            ## it can be time varying.  I'm adding a check above to ensure that alpha is
            ## a scalar or a vector of length N.
            if model['costFunction'].lower() == 'sse':
                residuals = (model['source'] - model['regressor'] * model['theta'])
                modelObj =  cvp.sum_squares( cvp.multiply( model['alpha'] ** .5 , residuals ) )
            elif model['costFunction'].lower() == 'l1':
                residuals = (model['source'] - model['regressor'] * model['theta'])
                modelObj =  cvp.norm( cvp.multiply( model['alpha'] , residuals ) ,1)
            elif model['costFunction'].lower()=='l2':
                residuals = (model['source'] - model['regressor'] * model['theta'])
                modelObj =  cvp.norm( cvp.multiply( model['alpha'] , residuals ) ,2)
            else:
                raise ValueError('{} wrong option, use "sse","l2" or "l1"'.format(costFunction))
            ## Define cost function to regularize theta ****************
            # ***** ***** ***** ***** ***** ***** ***** ***** ***** ***** ***** *
            # Check that beta is scalar or of length of number of parameters.
            model['beta'] = np.array(model['beta'])
            if model['beta'].size not in [1, model['order']]:
                raise ValueError('Beta must be scalar or vector with one element for each regressor')

            if model['regularizeTheta'] is not None:
                if callable(model['regularizeTheta']):
                    ## User can input their own function to regularize theta.
                    # Must input a cvxpy variable vector and output a scalar
                    # or a vector with one element for each parameter.

                    ## TODO: TRY CATCH TO ENSURE regularizeTheta WORKS AND RETURNS SCALAR
                    try:
                        regThetaObj = model['regularizeTheta'](model['theta']) * model['beta']
                    except:
                        raise ValueError('Check custom regularizer for model {}'.format(model['name']))
                    if regThetaObj.size[0]* regThetaObj.size[1] != 1:
                        raise ValueError('Check custom regularizer for model {}, make sure it returns a scalar'.format(model['name']))

                elif model['regularizeTheta'].lower() == 'l2':
                    ## Sum square errors.
                    regThetaObj = cvp.norm(model['theta'] * model['beta'])
                elif model['regularizeTheta'].lower() == 'l1':
                    regThetaObj = cvp.norm(model['theta'] * model['beta'], 1)
            else:
                regThetaObj = 0

            ## Define cost function to regularize source signal ****************
            # ***** ***** ***** ***** ***** ***** ***** ***** ***** ***** ***** *
            # Check that gamma is scalar
            model['gamma'] = np.array(model['gamma'])
            if model['gamma'].size != 1:
                raise NameError('Gamma must be scalar')

            ## Calculate regularization.
            if model['regularizeSource'] is not None:
                if callable(model['regularizeSource']):
                    ## User can input their own function to regularize the source signal.
                    # Must input a cvxpy variable vector and output a scalar.
                    regSourceObj = model['regularizeSource'](model['source']) * model['gamma']
                elif model['regularizeSource'].lower() == 'diff1_ss':
                    regSourceObj = cvp.sum_squares(cvp.diff(model['source'])) * model['gamma']
                else:
                    raise Exception('regularizeSource must be a callable method, \`diff1_ss\`, or None')
            else:
                regSourceObj = 0


            ## Sum total model objective
            model['obj'] = modelObj + regThetaObj + regSourceObj

            ## Append model to models list
            self.models[sourcename] = model

    def addConstraint(self, constraint):
        ### This is a method to add a new source
        """
        Implement add constraint behavior for CSSS instances.
        """
        self.constraints.append(constraint)

    def constructSolve(self):
        """
        Implement construct solve behavior for CSSS instances.
        """
        import cvxpy as cvp #cvxpy is a bad bad no good library and we only want to use it when we're using a model using this solver.

        ## This method constructs and solves the optimization

        ## Initialize objective function and modeled aggregate signal as 0
        obj = 0
        sum_sources = np.zeros((self.N,1))

        ## Initialize constraints as those custom created
        con = self.constraints

        ## For each model
        #    - Add cost to objective function
        #    - Add source to sum of sources
        #    - (TODO) Add custom constraints for each source
        for name, model in self.models.items():
            obj = obj + model['obj']
            sum_sources = sum_sources + model['source']
            ### ADD lb and ub constraints on individual source signal.
            if model['lb'] is not None:
                con.append(model['source'] >= model['lb'])
            if model['ub'] is not None:
                con.append(model['source'] <= model['ub'])


        ## Append the constraint that the sum of sources must equal aggergate signal
        con.append(np.vstack(self.aggregateSignal) == sum_sources)

        ## Solve problem
        prob = cvp.Problem(cvp.Minimize(obj), con)
        return prob.solve()

    def admmSolve(self,rho, MaxIter=500,ABSTOL= 1e-4,RELTOL=1e-1, verbose=False):
        ### This method constructs and solves the optimization using ADMM

        ### Add the coupling constraint using lagrangian
        ##  Do Gauss-Seidel pass across each source.
        #    - Add costs to objective costFunction.
        #    - Add costs for the equality constraint.
        #    - For each source, set the price and the remaining sources constant,
        #       - Add individual constraints to individual source updates,
        #       - Solve and update the source.
        """
        Implement admm solve behavior for CSSS instances.
        """
        import cvxpy as cvp #cvxpy is a bad bad no good library and we only want to use it when we're using a model using this solver.
        dual_objective=[]
        norm_resid_equality=[]
        aggregateSignalVector=np.array([[elem] for elem in self.aggregateSignal])
        overall_complexity=0
        if verbose:
            print('Verbose on')
        u=np.zeros((self.N,1))
        for k in range(0, MaxIter):
            for name, model in self.models.items():
                if k==0:
                    ### Initialize sources and old sources to zeros
                    model['admmSource']=np.zeros((self.N,1))
                    #model['admmTheta']=np.zeros((model['order'],1))
                    overall_complexity=overall_complexity+model['order']
                else:
                    ### Update each source by keeping the other sources constant
                    obj=0
                    con=[]
                    sum_sources = np.zeros((self.N,1))
                    for name_sub, model_sub in self.models.items():
                        ### For all the other sources, assume values constant
                        if name_sub!=name:
                            # residuals = (model['admmSource']
                            #     - (model['regressor'].dot( model['admmTheta'])))
                            sum_sources = sum_sources + model_sub['admmSource']
                        else:
                            ### This is the only source
                            ### we are solving for at each update
                            theta_update=cvp.Variable((model['order'], 1))
                            source_update=cvp.Variable((self.N, 1))

                            residuals = (source_update
                            - (model['regressor'] * theta_update))

                            if model['lb'] is not None:
                                con.append(source_update >= model['lb'])
                            if model['ub'] is not None:
                                con.append(source_update <= model['ub'])

                            sum_sources = sum_sources + source_update

                            ## MT TODO
                            # Why redefine the objective here?  Each source already has an
                            # objective defiend in the class, model_sub.obj.
                            obj=cvp.sum_squares(residuals) * model['alpha']

                    obj=obj+(rho/2)*cvp.sum_squares(sum_sources-aggregateSignalVector+u)
                    prob = cvp.Problem(cvp.Minimize(obj),con)
                    last_obj=prob.solve()
                    ### Update source
                    ## keep diff for tolerance
                    source_update_diff=source_update.value-self.models[name]['admmSource']
                    self.models[name]['admmSource']=source_update.value
                    #self.models[name]['admmTheta']=theta_update.value

            if k==0:
                if verbose:
                    print('Initialized all sources')
                    print("iter_num","s_norm","eps_dual","r_norm","eps_pri")

            else:
                dual_objective.append(last_obj)
                u=u+(sum_sources-aggregateSignalVector).value

                norm_resid=cvp.norm(sum_sources-aggregateSignalVector).value
                eps_pri = np.sqrt(overall_complexity)*ABSTOL
                + RELTOL*max(np.linalg.norm(sum_sources.value),np.linalg.norm(-aggregateSignalVector));
                norm_resid_equality.append(norm_resid)

                s_norm=np.linalg.norm(-rho*source_update_diff)
                eps_dual= np.sqrt(overall_complexity)*ABSTOL + RELTOL*np.linalg.norm(rho*u);


                if (verbose):
                    print(k, s_norm,eps_dual,norm_resid,eps_pri)


                if (s_norm<eps_dual) and (norm_resid<eps_pri):
                    break
                #print(np.transpose(y))
                #print(k, dual_objective)
        return dual_objective,norm_resid_equality,u

    def fixThetas(self):
        ## Fixes theta to current value and removes it as a decision variable
        ## This is creates the "real time problem.""
        """
        Implement fix thetas behavior for CSSS instances.
        """
        for name, m in self.models.items():
            m['theta'] = m['theta'].value
        self.updateSourceObj('all')
