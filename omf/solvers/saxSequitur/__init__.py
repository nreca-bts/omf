"""
Provide SAX and Sequitur time-series motif utilities used by anomaly-detection
workflows.
"""

import numpy as np

def cuts_for_asize(a_size):
    """Generate a set of alphabet cuts for its size."""

    options = {
        2: np.array([-np.inf,  0.00]),
        3: np.array([-np.inf, -0.4307273, 0.4307273]),
        4: np.array([-np.inf, -0.6744898, 0, 0.6744898]),
        5: np.array([-np.inf, -0.841621233572914, -0.2533471031358,
                    0.2533471031358, 0.841621233572914]),
        6: np.array([-np.inf, -0.967421566101701, -0.430727299295457, 0,
                    0.430727299295457, 0.967421566101701]),
        7: np.array([-np.inf, -1.06757052387814, -0.565948821932863,
                    -0.180012369792705, 0.180012369792705, 0.565948821932863,
                    1.06757052387814]),
        8: np.array([-np.inf, -1.15034938037601, -0.674489750196082,
                    -0.318639363964375, 0, 0.318639363964375,
                    0.674489750196082, 1.15034938037601]),
        9: np.array([-np.inf, -1.22064034884735, -0.764709673786387,
                    -0.430727299295457, -0.139710298881862, 0.139710298881862,
                    0.430727299295457, 0.764709673786387, 1.22064034884735]),
        10: np.array([-np.inf, -1.2815515655446, -0.841621233572914,
                     -0.524400512708041, -0.2533471031358, 0, 0.2533471031358,
                     0.524400512708041, 0.841621233572914, 1.2815515655446]),
        11: np.array([-np.inf, -1.33517773611894, -0.908457868537385,
                     -0.604585346583237, -0.348755695517045,
                     -0.114185294321428, 0.114185294321428, 0.348755695517045,
                     0.604585346583237, 0.908457868537385, 1.33517773611894]),
        12: np.array([-np.inf, -1.38299412710064, -0.967421566101701,
                     -0.674489750196082, -0.430727299295457,
                     -0.210428394247925, 0, 0.210428394247925,
                     0.430727299295457, 0.674489750196082, 0.967421566101701,
                     1.38299412710064]),
        13: np.array([-np.inf, -1.42607687227285, -1.0200762327862,
                     -0.736315917376129, -0.502402223373355,
                     -0.293381232121193, -0.0965586152896391,
                     0.0965586152896394, 0.293381232121194, 0.502402223373355,
                     0.73631591737613, 1.0200762327862, 1.42607687227285]),
        14: np.array([-np.inf, -1.46523379268552, -1.06757052387814,
                     -0.791638607743375, -0.565948821932863, -0.36610635680057,
                     -0.180012369792705, 0, 0.180012369792705,
                     0.36610635680057, 0.565948821932863, 0.791638607743375,
                     1.06757052387814, 1.46523379268552]),
        15: np.array([-np.inf, -1.50108594604402, -1.11077161663679,
                     -0.841621233572914, -0.622925723210088,
                     -0.430727299295457, -0.2533471031358, -0.0836517339071291,
                     0.0836517339071291, 0.2533471031358, 0.430727299295457,
                     0.622925723210088, 0.841621233572914, 1.11077161663679,
                     1.50108594604402]),
        16: np.array([-np.inf, -1.53412054435255, -1.15034938037601,
                     -0.887146559018876, -0.674489750196082,
                     -0.488776411114669, -0.318639363964375,
                     -0.157310684610171, 0, 0.157310684610171,
                     0.318639363964375, 0.488776411114669, 0.674489750196082,
                     0.887146559018876, 1.15034938037601, 1.53412054435255]),
        17: np.array([-np.inf, -1.5647264713618, -1.18683143275582,
                     -0.928899491647271, -0.721522283982343,
                     -0.541395085129088, -0.377391943828554,
                     -0.223007830940367, -0.0737912738082727,
                     0.0737912738082727, 0.223007830940367, 0.377391943828554,
                     0.541395085129088, 0.721522283982343, 0.928899491647271,
                     1.18683143275582, 1.5647264713618]),
        18: np.array([-np.inf, -1.59321881802305, -1.22064034884735,
                     -0.967421566101701, -0.764709673786387,
                     -0.589455797849779, -0.430727299295457,
                     -0.282216147062508, -0.139710298881862, 0,
                     0.139710298881862, 0.282216147062508, 0.430727299295457,
                     0.589455797849779, 0.764709673786387, 0.967421566101701,
                     1.22064034884735, 1.59321881802305]),
        19: np.array([-np.inf, -1.61985625863827, -1.25211952026522,
                     -1.00314796766253, -0.8045963803603, -0.633640000779701,
                     -0.47950565333095, -0.336038140371823, -0.199201324789267,
                     -0.0660118123758407, 0.0660118123758406,
                     0.199201324789267, 0.336038140371823, 0.47950565333095,
                     0.633640000779701, 0.8045963803603, 1.00314796766253,
                     1.25211952026522, 1.61985625863827]),
        20: np.array([-np.inf, -1.64485362695147, -1.2815515655446,
                     -1.03643338949379, -0.841621233572914, -0.674489750196082,
                     -0.524400512708041, -0.385320466407568, -0.2533471031358,
                     -0.125661346855074, 0, 0.125661346855074, 0.2533471031358,
                     0.385320466407568, 0.524400512708041, 0.674489750196082,
                     0.841621233572914, 1.03643338949379, 1.2815515655446,
                     1.64485362695147]),
    }

    return options[a_size]

def znorm(series, znorm_threshold=0.01):
    """Znorm implementation."""
    
    sd = np.std(series)
    if (sd < znorm_threshold):
        return series

    return (series - np.mean(series)) / sd

def idx2letter(idx):
    """Convert a numerical index to a char."""
    
    if 0 <= idx <= 20:
        return chr(96 + idx)
    else:
        raise ValueError('A wrong idx value supplied.')

def ts_to_string(series, cuts):
    """A straightforward num-to-string conversion."""
    
    sax = list()
    for i in range(0, len(series)):
    
        j = np.searchsorted(cuts,series[i])
        sax.append(idx2letter(j))
    
    return ''.join(sax)

def getSaxString(series, win_size, alphabet_size=3, z_threshold=0.01):
    """Simple via window conversion implementation."""
    
    cuts = cuts_for_asize(alphabet_size)
    
    saxString = ''
    for i in range(0, len(series) - win_size):

        sub_section = series[i:(i+win_size)]
        zn = znorm(sub_section, z_threshold)
        curr_word = ts_to_string(zn, cuts)
        saxString += ' ' + curr_word

    return saxString.strip()

def makeReplacement(stringArray, encodingGrammar, decodingGrammar, ruleNum, occurances):

    """
    Perform make replacement processing for the wrapped solver workflow.
    """
    ruleString = str(ruleNum)

    # go through each letter in the seq
    for i in range(len(stringArray)-1):

        # print('-------------------------------')
        # print('str: ', stringArray)
        # print('enc:' , encodingGrammar)
        # print('dec:' , decodingGrammar)
        # print('occ:' , occurances)

        # make a digram
        digram = ' '.join(stringArray[i:i+2])
    
        #print(digram)

        # if digram not in dict, add to dict 
        rule = encodingGrammar.get(digram)
        if rule is None:
            encodingGrammar[digram] = ''
        
        # else if digram in dict, but no rule 
        elif rule == '':

            # make rule
            encodingGrammar[digram] = ruleString
            decodingGrammar[ruleString] = digram

            # keep track of the locations of characters
            for letter in digram.split(' '):

                locations = occurances.get(letter)
                if locations is None:
                    occurances[letter] = [ruleString]
                else:
                    occurances[letter].append( ruleString )

            # replace all occurances of digram with rule, recursive call 

            stringSeq = ' '.join(stringArray)   
            stringSeq = stringSeq.replace(digram,ruleString)
            stringArray = stringSeq.split(' ')
            ruleNum += 1

            return ( stringArray, encodingGrammar, decodingGrammar, ruleNum, 
                occurances )

    return ( stringArray, encodingGrammar, decodingGrammar, ruleNum, 
                occurances )

def sequitur(stringArray, encodingGrammar, decodingGrammar, ruleNum, occurances):

    """
    Perform sequitur processing for the wrapped solver workflow.
    """
    ruleString = str(ruleNum)
    while len(stringArray) > 1:

        ( stringArray, encodingGrammar, decodingGrammar, ruleNum, 
        occurances ) = makeReplacement(stringArray, encodingGrammar, 
        decodingGrammar, ruleNum, occurances)

    # when length of seq string is 1
    # enforce rule utility
    toDelete = set([])
    for key in occurances.keys():

        numOccurances = len(occurances[key])
        if numOccurances == 1:

            rule = decodingGrammar.get(key)
            if rule is not None:
                replaceLocation = occurances[key][0]
                stringToReplace = decodingGrammar[replaceLocation]
                decodingGrammar[replaceLocation] = stringToReplace.replace(key,rule)
                toDelete.add(key)
                
    for key in toDelete:
        del decodingGrammar[key]
    
    return (stringArray, decodingGrammar)

def findAll( mainString, substring ):

    """
    Find the all that satisfies this workflow's search criteria.
    """
    locations = []
    startPoint = 0
    
    while True:

        firstLocation = mainString.find(substring, startPoint )
        if firstLocation == -1:
            break
        else:
            index = mainString[:firstLocation].count(' ')
            locations.append(index)
            startPoint = firstLocation + 1

    return locations

def getCounts(stringSeq, decodingGrammar):

    """
    Return the counts needed by this workflow.
    """
    repeats = np.zeros([len(stringSeq.split(' ')),1])
    occurances = {}

    numReplacements = 1
    while numReplacements != 0:
        numReplacements = 0
        for key in decodingGrammar.keys():
            value = decodingGrammar[key]
            for word in value.split(' '):
                replacement = decodingGrammar.get(word)
                if replacement is not None:
                    numReplacements += 1
                    decodingGrammar[key] = value.replace(word, replacement)

    originalAlphabet = list(set(stringSeq))
    for letter in originalAlphabet:
        if letter != ' ':
            decodingGrammar[letter] = letter

    for key in decodingGrammar.keys():
        value = decodingGrammar[key]
        occurances[value] = findAll(stringSeq,decodingGrammar[key])
        for location in occurances[value]:
                repeats[location] += len(occurances[value])

    # the occurance of the whole string is also counted above,
    # so remove this count from the total
    repeats[0] -= 1

    return (repeats, occurances)